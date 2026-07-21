"""Graph navigation under /graph.

Three subroutes:
  - /graph/paper        : find a paper (by id or by source+external_id) plus
                          its statements and dependency edges.
  - /graph/statement    : center the graph at a statement and traverse out.
  - /graph/embedding    : semantic search via slogan embeddings.
"""
import logging
import math
import os
import time
from typing import Dict, List, Literal, Optional, Tuple

import psycopg2
from fastapi import APIRouter, HTTPException, Query
from openai import OpenAI, RateLimitError

from db import rds_conn

logger = logging.getLogger(__name__)
from models import (
    StatementNode, DependencyEdge, SubgraphResponse, StatementRepresentation,
    StatementRoot,
    IdsRequest, StatementDetail, PaperDetail,
    GraphPaperReturn, GraphStatementReturn, GraphPaperResponse, Mode,
    PaperItem, StatementItem, DependencyItem,
    EmbeddingSearchResponse, EmbeddingSearchResult,
)

router = APIRouter()


# Maps paper.source → the source's metadata table, the column it keys on
# (always equals paper.external_id), and the fields we surface in PaperItem.
_SOURCE_METADATA = {
    "arXiv": {
        "table":   "arxiv_paper_metadata",
        "id_col":  "arxiv_id",
        "fields":  ["abstract", "journal_ref", "doi", "license"],
    },
    "Lean Community": {
        "table":   "lean_community_paper_metadata",
        "id_col":  "repo_slug",
        "fields":  ["repo_slug", "branch", "src_path"],
    },
    "Lean Graph": {
        "table":   "lean_graph_paper_metadata",
        "id_col":  "project_name",
        "fields":  ["project_name", "repo_url", "lean_toolchain",
                    "mathlib_rev", "git_commit", "extracted_at"],
    },
}

_ALL_PAPER_RETURN:     List[GraphPaperReturn]     = ["paper", "statements", "edges"]
_ALL_STATEMENT_RETURN: List[GraphStatementReturn] = ["root", "nodes", "edges"]
# `representations` is opt-in by default — it hits the embedding index and is
# heavier than the local subgraph fetch.

# Semantic-similarity cutoff for /graph/statement representations. Cosine
# similarity on qwen3-8b slogan embeddings; tune here if recall/precision is off.
_REPRESENTATION_SIMILARITY_THRESHOLD = 0.8

Direction = Literal["src", "dep", "both"]
Formality = Literal["informal", "formal"]


def _fetch_slogans(cur, statement_ids: list) -> Dict[str, str]:
    """First sufficient slogan per statement, keyed by statement_id."""
    if not statement_ids:
        return {}
    cur.execute(
        """
        SELECT DISTINCT ON (statement_id) statement_id, slogan
        FROM slogan
        WHERE statement_id = ANY(%s::uuid[])
          AND NOT insufficient_context
        ORDER BY statement_id, created_at
        """,
        (statement_ids,),
    )
    return {str(sid): text for sid, text in cur.fetchall()}


# ------------------------------------------------------------------ #
# /graph/statement — traverse                                         #
# ------------------------------------------------------------------ #

def _traverse(
    cur,
    start_ids: list,
    direction: Direction,
    formality: Formality,
) -> List[str]:
    """All statements reachable in one hop from ``start_ids`` (plus the
    origins themselves)."""
    dep_table = "formal_dependency" if formality == "formal" else "informal_dependency"
    # informal_dependency.dep_id can be NULL (unresolved cites); formal can't.
    out_filter = "" if formality == "formal" else "AND d.dep_id IS NOT NULL"

    out_sql = (
        f"SELECT d.dep_id "
        f"FROM {dep_table} d "
        f"WHERE d.src_id = ANY(%s::uuid[]) {out_filter}"
    )
    in_sql = (
        f"SELECT d.src_id "
        f"FROM {dep_table} d "
        f"WHERE d.dep_id = ANY(%s::uuid[])"
    )

    if direction == "src":
        neighbor_sql, params = out_sql, (start_ids,)
    elif direction == "dep":
        neighbor_sql, params = in_sql, (start_ids,)
    else:
        neighbor_sql, params = f"{out_sql} UNION {in_sql}", (start_ids, start_ids)

    cur.execute(
        f"""
        SELECT statement_id FROM (
            SELECT unnest(%s::uuid[]) AS statement_id
            UNION
            {neighbor_sql}
        ) t
        """,
        (start_ids, *params),
    )
    return [row[0] for row in cur.fetchall()]


def _build_subgraph(
    cur,
    node_ids: List[str],
    formality: Formality,
    mode: Mode,
) -> SubgraphResponse:
    if formality == "formal":
        if mode == "minimal":
            cur.execute(
                """
                SELECT s.statement_id
                FROM statement s
                WHERE s.statement_id = ANY(%s::uuid[])
                """,
                (node_ids,),
            )
            nodes = [StatementNode(statement_id=str(r[0])) for r in cur.fetchall()]
        else:
            cur.execute(
                """
                SELECT s.statement_id, fm.decl_name
                FROM statement s
                JOIN formal_metadata fm ON fm.statement_id = s.statement_id
                WHERE s.statement_id = ANY(%s::uuid[])
                """,
                (node_ids,),
            )
            stmt_rows = cur.fetchall()
            slogans = _fetch_slogans(cur, [r[0] for r in stmt_rows])
            nodes = [
                StatementNode(
                    statement_id=str(r[0]),
                    name=r[1] or f"<unnamed {str(r[0])[:8]}>",
                    slogan=slogans.get(str(r[0])),
                )
                for r in stmt_rows
            ]

        edge_cols = "src_id, dep_id" if mode == "minimal" else "src_id, dep_id, edge_type"
        cur.execute(
            f"""
            SELECT {edge_cols}
            FROM formal_dependency
            WHERE src_id = ANY(%s::uuid[])
            """,
            (node_ids,),
        )
        edges = [
            DependencyEdge(
                src_id=str(r[0]),
                dep_id=str(r[1]),
                edge_type=(r[2] if mode == "full" else None),
            )
            for r in cur.fetchall()
        ]
        return SubgraphResponse(nodes=nodes, edges=edges)

    # informal
    if mode == "minimal":
        cur.execute(
            """
            SELECT s.statement_id
            FROM statement s
            WHERE s.statement_id = ANY(%s::uuid[])
            """,
            (node_ids,),
        )
        nodes = [StatementNode(statement_id=str(r[0])) for r in cur.fetchall()]
    else:
        cur.execute(
            """
            SELECT s.statement_id, s.kind, im.ref
            FROM statement s
            LEFT JOIN informal_metadata im ON im.statement_id = s.statement_id
            WHERE s.statement_id = ANY(%s::uuid[])
            """,
            (node_ids,),
        )
        stmt_rows = cur.fetchall()
        slogans = _fetch_slogans(cur, [r[0] for r in stmt_rows])
        nodes = [
            StatementNode(
                statement_id=str(r[0]),
                name=r[1].capitalize() + (f" {r[2]}" if r[2] else ""),
                slogan=slogans.get(str(r[0])),
            )
            for r in stmt_rows
        ]

    if mode == "minimal":
        cur.execute(
            """
            SELECT d.src_id, d.dep_id, d.cite_id, d.cite_key
            FROM informal_dependency d
            WHERE d.src_id = ANY(%s::uuid[])
              AND (d.cite_key IS NULL OR d.cite_id IS NOT NULL)
            """,
            (node_ids,),
        )
        edges = [
            DependencyEdge(
                src_id=str(r[0]),
                dep_id=str(r[1]) if r[1] else None,
                cite_id=str(r[2]) if r[2] else None,
                cite_key=r[3],
            )
            for r in cur.fetchall()
        ]
    else:
        cur.execute(
            """
            SELECT d.src_id, d.dep_id, d.cite_id, d.cite_key,
                   d.dep_name, d.dep_key, d.location, d.methods
            FROM informal_dependency d
            WHERE d.src_id = ANY(%s::uuid[])
              AND (d.cite_key IS NULL OR d.cite_id IS NOT NULL)
            """,
            (node_ids,),
        )
        edges = [
            DependencyEdge(
                src_id=str(r[0]),
                dep_id=str(r[1]) if r[1] else None,
                cite_id=str(r[2]) if r[2] else None,
                cite_key=r[3],
                dep_name=r[4],
                dep_key=r[5],
                location=r[6],
                methods=r[7],
            )
            for r in cur.fetchall()
        ]
    return SubgraphResponse(nodes=nodes, edges=edges)


# ANN search for representations. Mirrors _EMBEDDING_SQL:
#   * query vector is a bound parameter (planner can match the HNSW index)
#   * slogan.model_name filter restricts to one canonical slogan per
#     statement, so the top-ann_k candidates cover ~ann_k *distinct*
#     statements instead of being inflated by per-statement slogan duplicates
#   * all filters (insufficient_context, paper_id exclusion, rep_sources)
#     live INSIDE the ann CTE alongside the ORDER BY/LIMIT, so iterative_scan
#     keeps fetching until ann_k rows that pass every filter are collected
#     rather than stopping at ann_k-by-distance and discarding the rest
_REPRESENTATIONS_SQL = """
WITH ann AS (
    SELECT
        st.statement_id,
        st.paper_id,
        p.source,
        e.embedding
    FROM embedding e
    JOIN slogan s     ON s.slogan_id    = e.slogan_id
    JOIN statement st ON st.statement_id = s.statement_id
    JOIN paper p      ON p.paper_id     = st.paper_id
    WHERE e.model_name = %(model)s
      AND s.model_name = ANY(%(slogan_models)s)
      AND NOT s.insufficient_context
      AND st.paper_id != %(exclude_paper)s
      AND (%(rep_sources)s::text[] IS NULL OR p.source = ANY(%(rep_sources)s))
    ORDER BY
        binary_quantize(e.embedding)::bit(4096)
        <~>
        binary_quantize(%(q)s::vector(4096))::bit(4096)
    LIMIT %(ann_k)s
),
ranked AS (
    SELECT
        statement_id,
        paper_id,
        source,
        1.0 - (embedding <=> %(q)s::vector(4096)) AS similarity
    FROM ann
),
deduped AS (
    SELECT DISTINCT ON (statement_id)
        statement_id, paper_id, source, similarity
    FROM ranked
    ORDER BY statement_id, similarity DESC
)
SELECT statement_id, paper_id, source, similarity
FROM deduped
WHERE similarity >= %(threshold)s
ORDER BY similarity DESC
LIMIT %(k)s;
"""


def _fetch_representations(
    cur,
    statement_id: str,
    n_representations: int,
    representation_sources: Optional[List[str]] = None,
) -> List[StatementRepresentation]:
    """Statements (from a different paper) whose slogan embedding is most
    similar to ``statement_id``'s, above ``_REPRESENTATION_SIMILARITY_THRESHOLD``.

    Two-stage: HNSW ANN by binary-quantized Hamming, then full-precision
    cosine rerank. Done as two round-trips (target vector fetch, then
    search) so the vector is a bound parameter and the HNSW index can be
    used — same pattern as /graph/embedding. Returns [] if the target has
    no sufficient slogan embedding under _EMBED_MODEL.
    """
    cur.execute(
        """
        SELECT e.embedding, s.paper_id
        FROM embedding e
        JOIN slogan sl   ON sl.slogan_id   = e.slogan_id
        JOIN statement s ON s.statement_id = sl.statement_id
        WHERE s.statement_id = %s
          AND e.model_name   = %s
          AND NOT sl.insufficient_context
        ORDER BY sl.created_at
        LIMIT 1
        """,
        (statement_id, _EMBED_MODEL),
    )
    row = cur.fetchone()
    if row is None:
        return []
    target_vec, target_paper_id = row

    # With slogan_models pinning to one slogan per statement, the top-ann_k
    # ANN candidates cover ~ann_k distinct statements; only a tiny handful
    # ever clear the similarity threshold (EXPLAIN on a real target: 7 of
    # 2000 pass >= 0.8). Bigger ann_k just buys more cold-cache I/O on the
    # HNSW index. 200 matches /graph/embedding and keeps the scan tight.
    ann_k = max(n_representations * 20, 200)
    cur.execute("SET LOCAL hnsw.ef_search = %s;", (min(ann_k, 1000),))

    # Representations are a "nice-to-have" enrichment on /graph/statement —
    # a slow or failing ANN scan should not 500 the whole endpoint. Wrap
    # the search in a SAVEPOINT so any failure (statement_timeout, an
    # unindexed source value, a malformed row) rolls back cleanly and we
    # return []. The transaction stays alive for the rest of the response.
    cur.execute("SAVEPOINT repr_search")
    try:
        cur.execute(
            _REPRESENTATIONS_SQL,
            {
                "q":             target_vec,
                "model":         _EMBED_MODEL,
                "slogan_models": _SLOGAN_MODELS,
                "exclude_paper": target_paper_id,
                "rep_sources":   representation_sources or None,
                "threshold":     _REPRESENTATION_SIMILARITY_THRESHOLD,
                "ann_k":         ann_k,
                "k":             n_representations,
            },
        )
        rows = cur.fetchall()
        cur.execute("RELEASE SAVEPOINT repr_search")
    except psycopg2.Error as e:
        cur.execute("ROLLBACK TO SAVEPOINT repr_search")
        cur.execute("RELEASE SAVEPOINT repr_search")
        logger.warning(
            "representations search failed for statement %s "
            "(sources=%r): %s: %s",
            statement_id, representation_sources, type(e).__name__, e,
        )
        return []

    return [
        StatementRepresentation(
            statement_id=str(r[0]),
            paper_id=str(r[1]),
            source=r[2],
            similarity=float(r[3]),
        )
        for r in rows
    ]


def _fetch_statement_root(cur, statement_id: str, mode: Mode) -> StatementRoot:
    """Hydrate the centered statement.

    minimal -> {statement_id, name}.
    full    -> minimal + nested StatementDetail and PaperDetail.
    """
    # One query covers both modes — informal_metadata for informal statements
    # and formal_metadata.decl_name for formal ones — so the same shape works
    # whether the caller knows the formality or not.
    cur.execute(
        """
        SELECT
            s.statement_id, s.formality, s.kind, s.body, s.proof,
            im.ref, im.note,
            fm.decl_name,
            p.paper_id, p.external_id, p.title, p.source, p.authors, p.url,
            apm.abstract
        FROM statement s
        JOIN paper p                         ON p.paper_id = s.paper_id
        LEFT JOIN informal_metadata im       ON im.statement_id = s.statement_id
        LEFT JOIN formal_metadata fm         ON fm.statement_id = s.statement_id
        LEFT JOIN arxiv_paper_metadata apm   ON apm.arxiv_id = p.external_id
        WHERE s.statement_id = %s
        """,
        (statement_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No statement with id '{statement_id}'")
    (sid, formality, kind, body, proof, ref, note, decl_name,
     paper_id, paper_ext_id, paper_title, paper_source, paper_authors, paper_url,
     paper_abstract) = row

    if formality == "formal":
        name = decl_name or f"<unnamed {str(sid)[:8]}>"
    else:
        name = kind.capitalize() + (f" {ref}" if ref else "")

    if mode == "minimal":
        return StatementRoot(statement_id=str(sid), name=name)

    return StatementRoot(
        statement_id=str(sid),
        name=name,
        statement=StatementDetail(
            statement_id=str(sid),
            kind=kind,
            ref=ref,
            body=body or "",
            proof=proof,
            note=note,
            paper_id=str(paper_id),
            paper_external_id=paper_ext_id,
            paper_title=paper_title,
        ),
        paper=PaperDetail(
            paper_id=str(paper_id),
            external_id=paper_ext_id,
            title=paper_title,
            authors=paper_authors or [],
            abstract=paper_abstract,
            url=paper_url,
            source=paper_source,
        ),
    )


@router.get("/graph/statement/{statement_id}", response_model=SubgraphResponse,
            response_model_exclude_none=True)
def graph_statement(
    statement_id: str,
    direction: Direction = Query(
        default="src",
        description=(
            "src: traverse what this statement depends on. "
            "dep: traverse what depends on this statement. "
            "both: union of the two."
        ),
    ),
    formality: Formality = Query(
        default="informal",
        description="Use informal_dependency or formal_dependency edges.",
    ),
    return_: Optional[List[GraphStatementReturn]] = Query(
        default=None,
        alias="return",
        description=(
            "Which top-level keys to populate: root, nodes, edges, representations. "
            "Repeat for multiple. Default: root+nodes+edges (representations is opt-in "
            "since it hits the embedding index)."
        ),
    ),
    n_representations: int = Query(
        default=10, ge=1, le=100,
        description="Max representations to return when 'representations' is requested.",
    ),
    representation_sources: List[str] = Query(
        default=[],
        description=(
            "Filter representations by paper.source (repeat for multiple), e.g. "
            "'arXiv', 'Lean Community'. Omit to search across all sources. "
            "Representations are always from a different paper than the centered "
            "statement's regardless of this filter."
        ),
    ),
    mode: Mode = Query(
        default="full",
        description=(
            "full: include node names/slogans, edge annotations, and full root details. "
            "minimal: return only IDs on nodes/edges and {statement_id, name} on root."
        ),
    ),
):
    chosen = set(return_ or _ALL_STATEMENT_RETURN)

    with rds_conn("v2") as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM statement WHERE statement_id = %s", (statement_id,))
        if cur.fetchone() is None:
            raise HTTPException(status_code=404, detail=f"No statement with id '{statement_id}'")

        root = _fetch_statement_root(cur, statement_id, mode) if "root" in chosen else None

        nodes = edges = None
        if "nodes" in chosen or "edges" in chosen:
            node_ids = _traverse(cur, [statement_id], direction, formality)
            sub = _build_subgraph(cur, node_ids, formality, mode)
            nodes = sub.nodes if "nodes" in chosen else None
            edges = sub.edges if "edges" in chosen else None

        representations = (
            _fetch_representations(
                cur, statement_id, n_representations,
                representation_sources=representation_sources or None,
            )
            if "representations" in chosen else None
        )

        return SubgraphResponse(
            root=root,
            nodes=nodes,
            edges=edges,
            representations=representations,
        )


# ------------------------------------------------------------------ #
# /graph/paper                                                        #
# ------------------------------------------------------------------ #

def _fetch_paper_item(cur, paper_id: str, mode: Mode) -> PaperItem:
    if mode == "minimal":
        cur.execute("SELECT paper_id, title FROM paper WHERE paper_id = %s", (paper_id,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"No paper with id '{paper_id}'")
        return PaperItem(paper_id=str(row[0]), title=row[1])

    cur.execute(
        """
        SELECT paper_id, kind, source, title, authors, url, external_id, categories, updated_at
        FROM paper WHERE paper_id = %s
        """,
        (paper_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No paper with id '{paper_id}'")

    data: Dict[str, object] = {
        "paper_id":    str(row[0]),
        "kind":        row[1],
        "source":      row[2],
        "title":       row[3],
        "authors":     row[4] or [],
        "url":         row[5],
        "external_id": row[6],
        "categories":  row[7] or [],
        "updated_at":  row[8],
    }

    cfg = _SOURCE_METADATA.get(row[2])
    if cfg and row[6] is not None:
        cur.execute(
            f"SELECT {', '.join(cfg['fields'])} "
            f"FROM {cfg['table']} WHERE {cfg['id_col']} = %s",
            (row[6],),
        )
        meta = cur.fetchone()
        if meta is not None:
            for field, value in zip(cfg["fields"], meta):
                data[field] = value

    return PaperItem(**data)


def _fetch_informal_statements(cur, paper_id: str, mode: Mode) -> List[StatementItem]:
    if mode == "minimal":
        cur.execute(
            """
            SELECT s.statement_id
            FROM statement s
            LEFT JOIN informal_metadata im ON im.statement_id = s.statement_id
            WHERE s.paper_id = %s AND s.formality = 'informal'
            ORDER BY im.ordinal
            """,
            (paper_id,),
        )
        return [StatementItem(statement_id=str(r[0])) for r in cur.fetchall()]

    cur.execute(
        """
        SELECT s.statement_id, s.formality, s.kind, s.body, s.proof,
               im.ref, im.note
        FROM statement s
        LEFT JOIN informal_metadata im ON im.statement_id = s.statement_id
        WHERE s.paper_id = %s AND s.formality = 'informal'
        ORDER BY im.ordinal
        """,
        (paper_id,),
    )
    rows = cur.fetchall()
    slogans = _fetch_slogans(cur, [r[0] for r in rows])
    return [
        StatementItem(
            statement_id=str(r[0]),
            formality=r[1],
            kind=r[2],
            name=r[2].capitalize() + (f" {r[5]}" if r[5] else ""),
            note=r[6],
            body=r[3],
            proof=r[4],
            slogan=slogans.get(str(r[0])),
        )
        for r in rows
    ]


def _fetch_formal_statements(cur, paper_id: str, mode: Mode) -> List[StatementItem]:
    def _name(decl_name: Optional[str], sid) -> str:
        return decl_name or f"<unnamed {str(sid)[:8]}>"

    if mode == "minimal":
        cur.execute(
            """
            SELECT s.statement_id
            FROM statement s
            JOIN formal_metadata fm ON fm.statement_id = s.statement_id
            WHERE s.paper_id = %s AND s.formality = 'formal'
            ORDER BY fm.decl_name
            """,
            (paper_id,),
        )
        return [StatementItem(statement_id=str(r[0])) for r in cur.fetchall()]

    cur.execute(
        """
        SELECT s.statement_id, s.formality, s.kind, s.body, s.proof,
               fm.decl_name, fm.module, fm.file_path, fm.docstring
        FROM statement s
        JOIN formal_metadata fm ON fm.statement_id = s.statement_id
        WHERE s.paper_id = %s AND s.formality = 'formal'
        ORDER BY fm.decl_name
        """,
        (paper_id,),
    )
    rows = cur.fetchall()
    slogans = _fetch_slogans(cur, [r[0] for r in rows])
    return [
        StatementItem(
            statement_id=str(r[0]),
            formality=r[1],
            kind=r[2],
            name=_name(r[5], r[0]),
            body=r[3],
            proof=r[4],
            slogan=slogans.get(str(r[0])),
            docstring=r[8],
            module=r[6],
            file_path=r[7],
        )
        for r in rows
    ]


def _fetch_informal_dependencies(cur, paper_id: str, mode: Mode) -> List[DependencyItem]:
    if mode == "minimal":
        cur.execute(
            """
            SELECT d.src_id, d.cite_id, d.dep_id, d.cite_key
            FROM informal_dependency d
            JOIN statement s ON s.statement_id = d.src_id
            WHERE s.paper_id = %s
              AND (d.cite_key IS NULL OR d.cite_id IS NOT NULL)
            """,
            (paper_id,),
        )
        return [
            DependencyItem(
                src_id=str(r[0]),
                cite_id=str(r[1]) if r[1] else None,
                dep_id=str(r[2]) if r[2] else None,
                cite_key=r[3],
            )
            for r in cur.fetchall()
        ]

    cur.execute(
        """
        SELECT d.src_id, d.cite_id, d.dep_id, d.cite_key, d.dep_key, d.dep_name,
               d.location, d.methods
        FROM informal_dependency d
        JOIN statement s ON s.statement_id = d.src_id
        WHERE s.paper_id = %s
          AND (d.cite_key IS NULL OR d.cite_id IS NOT NULL)
        """,
        (paper_id,),
    )
    return [
        DependencyItem(
            src_id=str(r[0]),
            cite_id=str(r[1]) if r[1] else None,
            dep_id=str(r[2]) if r[2] else None,
            cite_key=r[3],
            dep_key=r[4],
            dep_name=r[5],
            location=r[6],
            methods=r[7] or [],
        )
        for r in cur.fetchall()
    ]


def _fetch_formal_dependencies(cur, paper_id: str, mode: Mode) -> List[DependencyItem]:
    edge_cols = "d.src_id, d.dep_id" if mode == "minimal" else "d.src_id, d.dep_id, d.edge_type"
    cur.execute(
        f"""
        SELECT {edge_cols}
        FROM formal_dependency d
        JOIN statement s ON s.statement_id = d.src_id
        WHERE s.paper_id = %s
        """,
        (paper_id,),
    )
    return [
        DependencyItem(
            src_id=str(r[0]),
            dep_id=str(r[1]),
            edge_type=(r[2] if mode == "full" else None),
        )
        for r in cur.fetchall()
    ]


def _graph_paper_response(
    cur, paper_id: str, return_: List[GraphPaperReturn], mode: Mode,
) -> GraphPaperResponse:
    chosen = set(return_)
    cur.execute("SELECT kind FROM paper WHERE paper_id = %s", (paper_id,))
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No paper with id '{paper_id}'")
    is_formal = row[0] == "lean_repo"

    paper = _fetch_paper_item(cur, paper_id, mode) if "paper" in chosen else None
    statements_fn   = _fetch_formal_statements   if is_formal else _fetch_informal_statements
    dependencies_fn = _fetch_formal_dependencies if is_formal else _fetch_informal_dependencies
    return GraphPaperResponse(
        paper=paper,
        statements=statements_fn(cur, paper_id, mode) if "statements" in chosen else None,
        edges=dependencies_fn(cur, paper_id, mode) if "edges" in chosen else None,
    )


@router.get(
    "/graph/paper",
    response_model=GraphPaperResponse,
    response_model_exclude_none=True,
)
def graph_paper_by_source(
    external_id: str = Query(..., description="paper.external_id"),
    sources: List[str] = Query(
        default=[],
        description=(
            "Filter by paper.source (repeat for multiple), e.g. 'arXiv', "
            "'Lean Community'. If omitted, all sources are searched."
        ),
    ),
    return_: Optional[List[GraphPaperReturn]] = Query(
        default=None,
        alias="return",
        description=(
            "Which top-level keys to populate: paper, statements, edges. "
            "Repeat for multiple. Default: all three."
        ),
    ),
    mode: Mode = Query(
        default="full",
        description=(
            "full: include all metadata and source-specific fields. "
            "minimal: paper={paper_id,title}, statements=[{statement_id}], "
            "edges=[{src_id,dep_id,cite_id,cite_key}]."
        ),
    ),
):
    with rds_conn("v2") as conn, conn.cursor() as cur:
        if sources:
            cur.execute(
                "SELECT paper_id FROM paper WHERE external_id = %s AND source = ANY(%s)",
                (external_id, sources),
            )
        else:
            cur.execute(
                "SELECT paper_id FROM paper WHERE external_id = %s",
                (external_id,),
            )
        row = cur.fetchone()
        if row is None:
            detail = (
                f"No paper with external_id={external_id!r}"
                + (f" in sources={sources!r}" if sources else "")
            )
            raise HTTPException(status_code=404, detail=detail)
        return _graph_paper_response(cur, str(row[0]), return_ or _ALL_PAPER_RETURN, mode)


@router.get(
    "/graph/paper/{paper_id}",
    response_model=GraphPaperResponse,
    response_model_exclude_none=True,
)
def graph_paper(
    paper_id: str,
    return_: Optional[List[GraphPaperReturn]] = Query(
        default=None,
        alias="return",
        description=(
            "Which top-level keys to populate: paper, statements, edges. "
            "Repeat for multiple. Default: all three."
        ),
    ),
    mode: Mode = Query(
        default="full",
        description=(
            "full: include all metadata and source-specific fields. "
            "minimal: paper={paper_id,title}, statements=[{statement_id}], "
            "edges=[{src_id,dep_id,cite_id,cite_key}]."
        ),
    ),
):
    with rds_conn("v2") as conn, conn.cursor() as cur:
        return _graph_paper_response(cur, paper_id, return_ or _ALL_PAPER_RETURN, mode)


# ------------------------------------------------------------------ #
# /graph/embedding — semantic search                                  #
# ------------------------------------------------------------------ #

_EMBED_MODEL = "qwen3-8b"
_QUERY_INSTRUCTION = "Instruct: Given a math search query, retrieve theorems mathematically equivalent to the query.\nQuery: "
_SLOGAN_MODELS = ["qwen3-235b"]

_openai_client: Optional[OpenAI] = None
_model_cache: dict[str, Tuple[str, Optional[str]]] = {}


def _embed_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(
            base_url="https://api.studio.nebius.ai/v1/",
            api_key=os.environ["NEBIUS_API_KEY"],
        )
    return _openai_client


def _embed_model_info(model_alias: str) -> Tuple[str, Optional[str]]:
    if model_alias not in _model_cache:
        with rds_conn("v2") as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT model, instruction FROM embedding_model WHERE name = %s",
                (model_alias,),
            )
            row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Unknown embedding model: {model_alias}")
        _model_cache[model_alias] = (row[0], row[1])
    return _model_cache[model_alias]


def _embed_query(query: str) -> List[float]:
    """Embed and L2-normalize the query vector. Corpus embeddings are stored
    normalized (see embedding_model.normalized = TRUE for qwen3-8b); keeping
    the query side normalized too guarantees any consumer that takes a raw
    dot product gets a true cosine. pgvector's <=> already normalizes
    internally, but we don't want to depend on every code path going through
    it."""
    provider_model, _ = _embed_model_info(_EMBED_MODEL)
    input_text = _QUERY_INSTRUCTION + query
    last_exc: Exception = RuntimeError("no attempts made")
    for attempt in range(3):
        try:
            resp = _embed_client().embeddings.create(
                model=provider_model,
                input=input_text,
                encoding_format="float",
            )
            vec = resp.data[0].embedding
            norm = math.sqrt(sum(x * x for x in vec))
            return [x / norm for x in vec] if norm > 0 else vec
        except RateLimitError:
            raise  # propagate immediately so the route can return 429
        except Exception as e:
            last_exc = e
            if attempt < 2:
                delay = 0.5 * (attempt + 1)
                logger.warning(
                    "Nebius embed attempt %d failed, retrying in %.1fs: %s: %s",
                    attempt + 1, delay, type(e).__name__, e,
                )
                time.sleep(delay)
    raise last_exc


# Two-stage: binary-quantized HNSW narrows candidates by Hamming distance,
# then full-precision cosine reranks.
#
# All row-eliminating filters (source, kind, author, citations, in_journal,
# insufficient_context) live INSIDE the `ann` CTE, alongside the
# `ORDER BY <binary hamming> LIMIT ann_k`. This is load-bearing for recall:
# pgvector's iterative_scan only honors predicates in the same query as the
# index ORDER BY, so it keeps pulling candidates until ann_k rows that pass
# every filter are collected. Filtering in a downstream CTE (the old shape)
# let the index scan stop after ann_k rows by Hamming distance and then
# discarded the non-matching ones, collapsing the candidate pool whenever a
# filter was restrictive. This mirrors search.py, which pushes its source
# filter into the per-source ANN.
_EMBEDDING_SQL = """
WITH ann AS (
    SELECT
        st.statement_id,
        p.paper_id,
        INITCAP(st.kind) || COALESCE(' ' || im.ref, '') AS name,
        st.body,
        s.slogan,
        p.source,
        p.title,
        p.authors,
        p.url,
        p.external_id,
        apm.citation_count,
        e.embedding
    FROM embedding e
    JOIN slogan s     ON s.slogan_id = e.slogan_id
    JOIN statement st ON st.statement_id = s.statement_id
    JOIN paper p      ON p.paper_id = st.paper_id
    LEFT JOIN informal_metadata im     ON im.statement_id = st.statement_id
    LEFT JOIN arxiv_paper_metadata apm ON apm.arxiv_id = p.external_id
    WHERE e.model_name = %(model)s
      AND s.model_name = ANY(%(slogan_models)s)
      AND NOT s.insufficient_context
      AND (%(formality)s::text IS NULL OR st.formality = %(formality)s)
      AND (%(sources)s::text[] IS NULL OR p.source = ANY(%(sources)s))
      AND (%(types)s::text[]   IS NULL OR LOWER(st.kind) = ANY(%(types)s))
      AND (%(author_patterns)s::text[] IS NULL OR EXISTS (
              SELECT 1 FROM unnest(p.authors) a
              WHERE LOWER(a) LIKE ANY(%(author_patterns)s)
      ))
      AND COALESCE(apm.citation_count, 0) >= %(min_citations)s
      AND (%(in_journal)s::boolean IS NULL
           OR (apm.journal_ref IS NOT NULL) = %(in_journal)s)
    ORDER BY
        binary_quantize(e.embedding)::bit(4096)
        <~>
        binary_quantize(%(q)s::vector(4096))::bit(4096)
    LIMIT %(ann_k)s
),
ranked AS (
    SELECT
        statement_id,
        paper_id,
        name,
        body,
        slogan,
        source,
        title,
        authors,
        url,
        external_id,
        citation_count,
        1.0 - (embedding <=> %(q)s::vector(4096)) AS similarity
    FROM ann
    ORDER BY embedding <=> %(q)s::vector(4096)
    LIMIT %(top_k)s
)
SELECT *,
    similarity + %(cw)s * CASE
        WHEN COALESCE(citation_count, 0) > 0 THEN ln(COALESCE(citation_count, 0)::float)
        ELSE 0
    END AS score
FROM ranked
ORDER BY score DESC
LIMIT %(n)s;
"""

# Minimal mode: drop the SELECTed columns we don't need (name, body, slogan,
# source, title, authors, url, external_id, citation_count) — the join to
# informal_metadata and the paper-text columns are skipped entirely. paper and
# arxiv_paper_metadata are still joined to support the filter set. Filters live
# inside the `ann` CTE for the same recall reason as _EMBEDDING_SQL above.
_EMBEDDING_SQL_MINIMAL = """
WITH ann AS (
    SELECT
        st.statement_id,
        st.paper_id,
        apm.citation_count,
        e.embedding
    FROM embedding e
    JOIN slogan s     ON s.slogan_id = e.slogan_id
    JOIN statement st ON st.statement_id = s.statement_id
    JOIN paper p      ON p.paper_id = st.paper_id
    LEFT JOIN arxiv_paper_metadata apm ON apm.arxiv_id = p.external_id
    WHERE e.model_name = %(model)s
      AND s.model_name = ANY(%(slogan_models)s)
      AND NOT s.insufficient_context
      AND (%(formality)s::text IS NULL OR st.formality = %(formality)s)
      AND (%(sources)s::text[] IS NULL OR p.source = ANY(%(sources)s))
      AND (%(types)s::text[]   IS NULL OR LOWER(st.kind) = ANY(%(types)s))
      AND (%(author_patterns)s::text[] IS NULL OR EXISTS (
              SELECT 1 FROM unnest(p.authors) a
              WHERE LOWER(a) LIKE ANY(%(author_patterns)s)
      ))
      AND COALESCE(apm.citation_count, 0) >= %(min_citations)s
      AND (%(in_journal)s::boolean IS NULL
           OR (apm.journal_ref IS NOT NULL) = %(in_journal)s)
    ORDER BY
        binary_quantize(e.embedding)::bit(4096)
        <~>
        binary_quantize(%(q)s::vector(4096))::bit(4096)
    LIMIT %(ann_k)s
),
ranked AS (
    SELECT
        statement_id,
        paper_id,
        citation_count,
        1.0 - (embedding <=> %(q)s::vector(4096)) AS similarity
    FROM ann
    ORDER BY embedding <=> %(q)s::vector(4096)
    LIMIT %(top_k)s
)
SELECT statement_id, paper_id, similarity,
    similarity + %(cw)s * CASE
        WHEN COALESCE(citation_count, 0) > 0 THEN ln(COALESCE(citation_count, 0)::float)
        ELSE 0
    END AS score
FROM ranked
ORDER BY score DESC
LIMIT %(n)s;
"""


@router.get("/graph/embedding", response_model=EmbeddingSearchResponse,
            response_model_exclude_none=True)
def graph_embedding(
    query: str = Query(..., min_length=1, description="Natural-language search query."),
    n_results: int = Query(10, ge=1, le=100),
    formality: Literal["informal", "formal", "both"] = Query(
        "both",
        description=(
            "Filter results by statement formality: 'informal', 'formal', or "
            "'both' (default, no filter)."
        ),
    ),
    sources: List[str] = Query(default=[], description="Paper sources, e.g. 'arXiv'."),
    types: List[str] = Query(default=[], description="Statement kinds, e.g. theorem, lemma."),
    authors: List[str] = Query(default=[], description="Author substring filter."),
    min_citations: int = Query(0, ge=0),
    citation_weight: float = Query(0.0, ge=0.0),
    in_journal: Optional[bool] = Query(None),
    mode: Mode = Query(
        default="full",
        description=(
            "full: include name, body, slogan, paper title/authors/url/source, citation_count. "
            "minimal: only statement_id, paper_id, similarity, score."
        ),
    ),
):
    try:
        query_vec = _embed_query(query)
        top_k = n_results * 5
        ann_k = max(top_k * 4, 200)

        params = {
            "q":               query_vec,
            "model":           _EMBED_MODEL,
            "slogan_models":   _SLOGAN_MODELS,
            "formality":       None if formality == "both" else formality,
            "sources":         sources or None,
            "types":           [t.lower() for t in types] or None,
            "author_patterns": [f"%{a.lower()}%" for a in authors] or None,
            "min_citations":   min_citations,
            "in_journal":      in_journal,
            "cw":              citation_weight,
            "ann_k":           ann_k,
            "top_k":           top_k,
            "n":               n_results,
        }

        sql = _EMBEDDING_SQL_MINIMAL if mode == "minimal" else _EMBEDDING_SQL
        with rds_conn("v2") as conn, conn.cursor() as cur:
            # At large n_results (ann_k can reach a few thousand), the HNSW
            # iterative_scan over the binary-quantized index can run longer
            # than the default 10s statement_timeout. Lift it to 60s for
            # this transaction only; the request itself is still subject
            # to FastAPI's normal request timeouts.
            cur.execute("SET LOCAL statement_timeout = '60000';")
            # hnsw.ef_search has a hard upper bound of 1000 in pgvector;
            # at large n_results, ann_k can exceed that and the SET fails.
            cur.execute("SET LOCAL hnsw.ef_search = %s;", (min(max(ann_k, 200), 1000),))
            cur.execute("SET LOCAL hnsw.iterative_scan = 'relaxed_order';")
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]

        if mode == "minimal":
            return EmbeddingSearchResponse(results=[
                EmbeddingSearchResult(
                    statement_id=str(r["statement_id"]),
                    paper_id=str(r["paper_id"]),
                    similarity=float(r["similarity"]),
                    score=float(r["score"]),
                )
                for r in rows
            ])

        return EmbeddingSearchResponse(results=[
            EmbeddingSearchResult(
                statement_id=str(r["statement_id"]),
                paper_id=str(r["paper_id"]),
                name=r["name"],
                body=r["body"],
                slogan=r["slogan"],
                source=r["source"],
                title=r["title"],
                authors=r["authors"] or [],
                url=r["url"],
                external_id=r["external_id"],
                citation_count=r["citation_count"],
                similarity=float(r["similarity"]),
                score=float(r["score"]),
            )
            for r in rows
        ])
    except HTTPException:
        raise
    except RateLimitError as e:
        logger.warning("/graph/embedding rate-limited by Nebius: %s", e)
        raise HTTPException(status_code=429, detail="Embedding API rate limit reached; back off and retry.")
    except Exception as e:
        logger.exception("/graph/embedding failed for query %r", query)
        raise HTTPException(status_code=500, detail="Internal error running embedding search.")


# ------------------------------------------------------------------ #
# Hydration (single + batch) — not graph navigation; kept at root.    #
# ------------------------------------------------------------------ #

@router.get("/statement/{statement_id}", response_model=StatementDetail)
def get_statement(statement_id: str):
    with rds_conn("v2") as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.statement_id, s.kind, s.body, s.proof,
                   im.ref, im.note,
                   p.paper_id, p.external_id, p.title
            FROM statement s
            LEFT JOIN informal_metadata im ON im.statement_id = s.statement_id
            JOIN paper p ON p.paper_id = s.paper_id
            WHERE s.statement_id = %s
            """,
            (statement_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No statement with id '{statement_id}'")
    sid, kind, body, proof, ref, note, paper_id, paper_ext_id, paper_title = row
    return StatementDetail(
        statement_id=str(sid),
        kind=kind,
        ref=ref,
        body=body or "",
        proof=proof,
        note=note,
        paper_id=str(paper_id),
        paper_external_id=paper_ext_id,
        paper_title=paper_title,
    )


@router.get("/paper/{paper_id}", response_model=PaperDetail)
def get_paper(paper_id: str):
    with rds_conn("v2") as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.paper_id, p.external_id, p.title, p.authors, p.url, p.source,
                   apm.abstract
            FROM paper p
            LEFT JOIN arxiv_paper_metadata apm ON apm.arxiv_id = p.external_id
            WHERE p.paper_id = %s
            """,
            (paper_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No paper with id '{paper_id}'")
    pid, ext_id, title, authors, url, source, abstract = row
    return PaperDetail(
        paper_id=str(pid),
        external_id=ext_id,
        title=title,
        authors=authors or [],
        url=url,
        source=source,
        abstract=abstract,
    )


@router.post("/statements", response_model=List[StatementDetail])
def batch_statements(body: IdsRequest):
    if not body.ids:
        return []
    with rds_conn("v2") as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.statement_id, s.kind, s.body, s.proof,
                   im.ref, im.note,
                   p.paper_id, p.external_id, p.title
            FROM statement s
            LEFT JOIN informal_metadata im ON im.statement_id = s.statement_id
            JOIN paper p ON p.paper_id = s.paper_id
            WHERE s.statement_id = ANY(%s::uuid[])
            """,
            (body.ids,),
        )
        rows = cur.fetchall()
    return [
        StatementDetail(
            statement_id=str(r[0]),
            kind=r[1],
            body=r[2] or "",
            proof=r[3],
            ref=r[4],
            note=r[5],
            paper_id=str(r[6]),
            paper_external_id=r[7],
            paper_title=r[8],
        )
        for r in rows
    ]


@router.post("/papers", response_model=List[PaperDetail])
def batch_papers(body: IdsRequest):
    if not body.ids:
        return []
    with rds_conn("v2") as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.paper_id, p.external_id, p.title, p.authors, p.url, p.source,
                   apm.abstract
            FROM paper p
            LEFT JOIN arxiv_paper_metadata apm ON apm.arxiv_id = p.external_id
            WHERE p.paper_id = ANY(%s::uuid[])
            """,
            (body.ids,),
        )
        rows = cur.fetchall()
    return [
        PaperDetail(
            paper_id=str(r[0]),
            external_id=r[1],
            title=r[2],
            authors=r[3] or [],
            url=r[4],
            source=r[5],
            abstract=r[6],
        )
        for r in rows
    ]


@router.get("/papers")
def list_papers():
    with rds_conn("v2") as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.paper_id, p.title, p.external_id, p.source, p.url,
                   COUNT(s.statement_id) AS statement_count
            FROM ag_papers_100 p
            LEFT JOIN statement s ON s.paper_id = p.paper_id
            GROUP BY p.paper_id, p.title, p.external_id, p.source, p.url
            ORDER BY p.title
            """
        )
        rows = cur.fetchall()
    return {
        "papers": [
            {
                "paper_id": str(r[0]),
                "title": r[1],
                "external_id": r[2],
                "source": r[3],
                "url": r[4],
                "statement_count": r[5],
            }
            for r in rows
        ]
    }
