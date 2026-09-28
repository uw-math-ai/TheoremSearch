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
import re
import time
from datetime import datetime, timezone
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


# ANN search for representations. Mirrors the ANN path of _embedding_sql:
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


# Mirrors the SQL search_kind() used to build statement_search.kind (the formal
# ingesters disagree: theorem/thm, definition/def, ...). Normalizing here keeps
# the filter a plain text[] the planner can estimate, instead of hiding it in
# ARRAY(SELECT search_kind(...)) — which cost 25s cold on the website's
# default four-type filter.
_KIND_ALIASES = {
    "thm": "theorem", "def": "definition", "inst": "instance",
    "struct": "structure", "ctor": "constructor",
}


def _search_kinds(types: List[str]) -> List[str]:
    return sorted({_KIND_ALIASES.get(t.lower(), t.lower()) for t in types})


_ARXIV_RE = re.compile(
    r'(?:arxiv\.org/(?:abs|pdf)/)?(\d{4}\.\d{4,5}|[a-z\-]+/\d{7})', re.IGNORECASE
)


def _parse_paper_filter(raw: str):
    """Split a comma-separated paper filter string into (arXiv id prefixes, title substrings)."""
    ids: List[str] = []
    titles: List[str] = []
    if not raw or not raw.strip():
        return ids, titles
    for token in [t.strip() for t in raw.split(',') if t.strip()]:
        m = _ARXIV_RE.search(token)
        if m:
            ids.append(m.group(1).lower())
        else:
            titles.append(token.lower())
    return ids, titles


# Filters for /graph/embedding. The semantics mirror the theoremsearch.com
# search filters (theorem-search-app app/api/search/route.ts), so the website
# can proxy its search through this route:
#   - year / publication-status filters let through papers that have no value
#     for that field (non-arXiv sources), instead of silently dropping them;
#   - citation filters treat an unknown count as 0 unless
#     include_unknown_citations says otherwise.
# Only the active filters are emitted: generic `(%(x)s IS NULL OR ...)` guards
# hide the real predicates from the planner's selectivity estimates.
# Paper-level clauses expect `p` = paper and `apm` = arxiv_paper_metadata
# LEFT JOINed on external_id; they also pre-select papers on their own (see
# _paper_prefilter_sql).
def _paper_clauses(p: dict) -> List[str]:
    clauses = []
    if p["sources"]:
        clauses.append("p.source = ANY(%(sources)s)")
    if p["author_patterns"]:
        # Matched against the joined author list so the trigram index
        # idx_paper_authors_trgm can serve the LIKE (see rds/helpers/indexes.sql);
        # EXISTS over unnest(authors) cannot be indexed and scanned all of paper.
        clauses.append("authors_text(p.authors) LIKE ANY(%(author_patterns)s)")
    if p["categories"]:
        clauses.append("p.categories[1] = ANY(%(categories)s)")
    if p["updated_from"]:
        clauses.append("(p.updated_at IS NULL OR p.updated_at >= %(updated_from)s)")
    if p["updated_before"]:
        clauses.append("(p.updated_at IS NULL OR p.updated_at < %(updated_before)s)")
    if p["in_journal"] is not None:
        clauses.append("(apm.arxiv_id IS NULL OR (apm.journal_ref IS NOT NULL) = %(in_journal)s)")
    if p["min_citations"] > 0 or p["citation_max"] is not None or p["unknown_citations"] is False:
        known = "apm.citation_count BETWEEN %(min_citations)s AND %(citation_max_or_inf)s"
        if p["unknown_citations"] is None:
            clauses.append("COALESCE(apm.citation_count, 0) BETWEEN %(min_citations)s AND %(citation_max_or_inf)s")
        elif p["unknown_citations"]:
            clauses.append(f"(apm.citation_count IS NULL OR {known})")
        else:
            clauses.append(known)
    paper = []
    if p["paper_ids"]:
        paper.append("LOWER(p.external_id) LIKE ANY(%(paper_ids)s)")
    if p["paper_titles"]:
        paper.append("LOWER(p.title) LIKE ANY(%(paper_titles)s)")
    if paper:
        clauses.append("(" + " OR ".join(paper) + ")")
    return clauses


def _search_clauses(p: dict) -> List[str]:
    """The /graph/embedding filters over statement_search (alias `ss`), which
    carries the paper-level filter columns next to each embedding. Same
    semantics as _paper_clauses."""
    clauses = []
    if p["formality"]:
        clauses.append("ss.formality = %(formality)s::formality_kind")
    if p["types"]:
        clauses.append("ss.kind = ANY(%(types)s)")
    if p["sources"]:
        clauses.append("ss.source = ANY(%(sources)s)")
    if p["categories"]:
        clauses.append("ss.primary_category = ANY(%(categories)s)")
    if p["year_min"] is not None:
        clauses.append("(ss.year IS NULL OR ss.year >= %(year_min)s)")
    if p["year_max"] is not None:
        clauses.append("(ss.year IS NULL OR ss.year <= %(year_max)s)")
    if p["in_journal"] is not None:
        clauses.append("(ss.in_journal IS NULL OR ss.in_journal = %(in_journal)s)")
    if p["min_citations"] > 0 or p["citation_max"] is not None or p["unknown_citations"] is False:
        known = "ss.citation_count BETWEEN %(min_citations)s AND %(citation_max_or_inf)s"
        if p["unknown_citations"] is None:
            clauses.append("COALESCE(ss.citation_count, 0) BETWEEN %(min_citations)s AND %(citation_max_or_inf)s")
        elif p["unknown_citations"]:
            clauses.append(f"(ss.citation_count IS NULL OR {known})")
        else:
            clauses.append(known)
    if p["paper_uuids"]:
        clauses.append("ss.paper_id = ANY(%(paper_uuids)s::uuid[])")
    return clauses


# Selective paper-level filters (authors, paper_filter) are resolved to a
# paper_id list first. Those filters can't be answered from the HNSW index:
# iterative_scan gives up after hnsw.max_scan_tuples candidates, which for an
# author or a single paper is long before it finds any matches, so the old
# single-query shape returned few or no results. With the papers known up
# front, their statements are few enough to rank exactly by full-precision
# cosine instead.
def _paper_prefilter_sql(p: dict) -> str:
    return f"""
SELECT p.paper_id
FROM paper p
LEFT JOIN arxiv_paper_metadata apm ON apm.arxiv_id = p.external_id
WHERE {" AND ".join(_paper_clauses(p))}
LIMIT %(prefilter_limit)s
"""

# How many index candidates a filtered HNSW iterative scan may visit before
# giving up (pgvector default: 20000). The filters are columns of the indexed
# table, so each candidate costs one heap-tuple check.
_HNSW_MAX_SCAN_TUPLES = 50000

# Rank the filtered rows exactly (no graph walk) while the planner expects at
# most this many to match a branch. Costs roughly 3us/row, so ~1s at the
# threshold; above it the HNSW walk is both faster and finds enough matches.
_EXACT_MAX_ROWS = 300_000

# Candidates (closest by Hamming distance) that get the full-precision cosine
# rerank, as a multiple of n_results, with a floor. Each one is a ~16KB random
# read of embedding.embedding, so this is the query's dominant cost whenever
# those vectors aren't cached.
#
# Measured over 10 queries x 5 filter sets against reranking every candidate
# (top-20 overlap; the top hit was identical at every setting):
#
#   multiple of n_results    2x     3x     4x     5x    7.5x
#   overlap, worst filter  0.940  0.965  0.965  0.965  0.990
#   overlap, typical       0.980  1.000  1.000  0.995  0.995
#
# 8x keeps overlap at ~0.99 while reading ~60% fewer vectors than the
# untrimmed shape (which reranked up to ann_k per source branch).
_RERANK_PER_RESULT = 8
_RERANK_MIN = 120

# Beyond this many matching papers, fall back to the HNSW path (the exact
# rerank would have to read too many 16KB vectors).
_PREFILTER_MAX_PAPERS = 2000

_FULL_COLUMNS = """
        -- formal statements are named by their Lean declaration (as in
        -- /graph/statement); informal ones by kind + ref.
        COALESCE(fm.decl_name, INITCAP(st.kind) || COALESCE(' ' || im.ref, '')) AS name,
        -- normalized like statement_search.kind, so a client that filters
        -- types=theorem doesn't get kind='thm' back
        search_kind(st.kind) AS kind,
        st.formality::text AS formality,
        st.body,
        s.slogan,
        p.source,
        p.title,
        p.authors,
        COALESCE(im.url, p.url) AS url,  -- statement page when the source has one
        p.external_id,
        p.categories,
        EXTRACT(YEAR FROM p.updated_at)::int AS year,
        apm.journal_ref,
        apm.citation_count,"""

_MINIMAL_COLUMNS = """
        apm.citation_count,"""


def _source_branches(p: dict) -> List[str]:
    """Partial-index predicates to search. Each must appear verbatim for the
    planner to pick the matching partial HNSW index."""
    branches = []
    if not p["sources"] or "arXiv" in p["sources"]:
        branches.append("ss.source = 'arXiv'")
    if not p["sources"] or any(src != "arXiv" for src in p["sources"]):
        branches.append("ss.source <> 'arXiv'")
    return branches


def _estimate_rows(cur, branch: str, p: dict, params: dict) -> float:
    """Planner's row estimate for one branch's filters. Plan-only; the query
    is never executed."""
    where = " AND ".join([branch] + _search_clauses(p))
    cur.execute(f"EXPLAIN (FORMAT JSON) SELECT 1 FROM statement_search ss WHERE {where}", params)
    return cur.fetchone()[0][0]["Plan"]["Plan Rows"]


def _candidate_sql(branch: str, where: List[str], exact: bool) -> str:
    """Candidates for one branch, ordered by Hamming distance to the query.

    exact=False walks the partial HNSW index. pgvector's iterative scan
    re-walks until ann_k rows pass the filters, but gives up after
    hnsw.max_scan_tuples, so a filter matching a small share of the branch
    returns far fewer than ann_k rows (math.CT: 14 of 400, and raising the
    scan limits cost 15-60s for a handful more).

    exact=True instead collects every matching row (btree) and ranks it by
    exact Hamming distance. The quantized vectors are 512 bytes and stored
    inline, so that is cheap while the filtered set is small — 90k rows in
    0.3s, versus 15.5s and 1/28th the candidates via the graph. The
    MATERIALIZED fence stops the planner folding this back into an index
    scan on the ORDER BY.
    """
    filters = " AND ".join([branch] + where)
    order = "bq <~> binary_quantize(%(q)s::vector(4096))::bit(4096)"
    if exact:
        return f"""    (WITH filtered AS MATERIALIZED (
         SELECT embedding_id, statement_id, bq FROM statement_search ss WHERE {filters}
     )
     SELECT embedding_id, statement_id, {order} AS hamming FROM filtered ORDER BY {order} LIMIT %(ann_k)s)"""
    return f"""    (SELECT ss.embedding_id, ss.statement_id, ss.{order} AS hamming
     FROM statement_search ss
     WHERE {filters}
     ORDER BY ss.{order}
     LIMIT %(ann_k)s)"""


def _embedding_sql(p: dict, mode: str, shapes: List[Tuple[str, bool]]) -> str:
    """Build the /graph/embedding query over statement_search.

    `shapes` pairs each source branch with how to get its candidates (see
    _candidate_sql). The candidates closest by Hamming distance are then
    reranked by full-precision cosine (embedding.embedding), keeping each
    statement's closest embedding (formal statements can have one per slogan
    prompt).

    Only `rerank_k` candidates are reranked: each one costs a random read of
    a 4096-dim vector (~16KB, TOASTed), so reranking everything the branches
    return was the most expensive part of the query.
    """
    where = _search_clauses(p)
    candidates = "\n    UNION ALL\n".join(
        _candidate_sql(branch, where, exact) for branch, exact in shapes
    )
    full = mode == "full"
    return f"""
WITH candidates AS (
{candidates}
),
trimmed AS (
    SELECT DISTINCT ON (statement_id) embedding_id, statement_id
    FROM (SELECT * FROM candidates ORDER BY hamming LIMIT %(rerank_k)s) c
    ORDER BY statement_id, hamming
),
reranked AS (
    SELECT
        c.statement_id, e.slogan_id,
        1.0 - (e.embedding <=> %(q)s::vector(4096)) AS similarity
    FROM trimmed c
    JOIN embedding e ON e.embedding_id = c.embedding_id
),
top AS (
    SELECT * FROM reranked ORDER BY similarity DESC LIMIT %(top_k)s
)
SELECT
    st.statement_id,
    p.paper_id,{_FULL_COLUMNS if full else _MINIMAL_COLUMNS}
    top.similarity,
    top.similarity + %(cw)s * CASE
        WHEN COALESCE(apm.citation_count, 0) > 0 THEN ln(apm.citation_count::float)
        ELSE 0
    END AS score
FROM top
JOIN statement st ON st.statement_id = top.statement_id
JOIN paper p      ON p.paper_id = st.paper_id
{"JOIN slogan s ON s.slogan_id = top.slogan_id" if full else ""}
{"LEFT JOIN informal_metadata im ON im.statement_id = st.statement_id" if full else ""}
{"LEFT JOIN formal_metadata fm   ON fm.statement_id = st.statement_id" if full else ""}
LEFT JOIN arxiv_paper_metadata apm ON apm.arxiv_id = p.external_id
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
    sources: List[str] = Query(default=[], description="Paper sources, e.g. 'arXiv'. Repeat for multiple."),
    types: List[str] = Query(default=[], description="Statement kinds, e.g. theorem, lemma. Repeat for multiple."),
    authors: List[str] = Query(default=[], description="Author substring filter. Repeat for multiple (any match)."),
    min_citations: int = Query(0, ge=0),
    citation_max: Optional[int] = Query(default=None, ge=0, description="Maximum citation count."),
    include_unknown_citations: Optional[bool] = Query(
        default=None,
        description=(
            "How to treat papers with no known citation count (all non-arXiv "
            "sources). true: always include; false: always exclude; unset: "
            "count them as 0 citations."
        ),
    ),
    citation_weight: float = Query(0.0, ge=0.0),
    in_journal: Optional[bool] = Query(
        None,
        description=(
            "true: only papers with a journal reference; false: only preprints. "
            "Sources without publication metadata pass either way."
        ),
    ),
    categories: List[str] = Query(
        default=[],
        description="Primary arXiv category, e.g. 'math.NT'. Repeat for multiple.",
    ),
    year_min: Optional[int] = Query(
        default=None, ge=1900, le=9999,
        description="Earliest year of the paper's latest version. Papers with no date always pass.",
    ),
    year_max: Optional[int] = Query(
        default=None, ge=1900, le=9998,
        description="Latest year of the paper's latest version. Papers with no date always pass.",
    ),
    paper_filter: Optional[str] = Query(
        default=None,
        description=(
            "Comma-separated arXiv IDs or title substrings to restrict results to specific papers. "
            "arXiv IDs are matched as prefix (e.g. '2301.12345'); other tokens match title substrings."
        ),
    ),
    mode: Mode = Query(
        default="full",
        description=(
            "full: include name, kind, formality, body, slogan, paper title/authors/url/source/"
            "categories/year/journal_ref, citation_count. "
            "minimal: only statement_id, paper_id, similarity, score."
        ),
    ),
):
    try:
        query_vec = _embed_query(query)
        top_k = n_results * 5
        ann_k = max(top_k * 4, 200)

        paper_ids, paper_titles = _parse_paper_filter(paper_filter or "")
        params = {
            "q":                 query_vec,
            "model":             _EMBED_MODEL,
            "slogan_models":     _SLOGAN_MODELS,
            "formality":         None if formality == "both" else formality,
            "sources":           sources or None,
            "types":             _search_kinds(types) or None,
            "author_patterns":   [f"%{a.lower()}%" for a in authors] or None,
            "categories":        categories or None,
            "updated_from":      datetime(year_min, 1, 1, tzinfo=timezone.utc) if year_min else None,
            "updated_before":    datetime(year_max + 1, 1, 1, tzinfo=timezone.utc) if year_max else None,
            "year_min":          year_min,
            "year_max":          year_max,
            "in_journal":        in_journal,
            "min_citations":     min_citations,
            "citation_max":      citation_max,
            "citation_max_or_inf": citation_max if citation_max is not None else 2**31 - 1,
            "unknown_citations": include_unknown_citations,
            "paper_ids":         [id_ + "%" for id_ in paper_ids] or None,
            "paper_titles":      [f"%{t}%" for t in paper_titles] or None,
            "paper_uuids":       None,
            "prefilter_limit":   _PREFILTER_MAX_PAPERS + 1,
            "cw":                citation_weight,
            "ann_k":             ann_k,
            "rerank_k":          max(n_results * _RERANK_PER_RESULT, _RERANK_MIN),
            "top_k":             top_k,
            "n":                 n_results,
        }

        with rds_conn("v2") as conn, conn.cursor() as cur:
            # At large n_results (ann_k can reach a few thousand), the HNSW
            # iterative_scan over the binary-quantized index can run longer
            # than the default 10s statement_timeout. Lift it to 60s for
            # this transaction only; the request itself is still subject
            # to FastAPI's normal request timeouts.
            cur.execute("SET LOCAL statement_timeout = '60000';")

            if params["author_patterns"] or params["paper_ids"] or params["paper_titles"]:
                cur.execute(_paper_prefilter_sql(params), params)
                matched = [r[0] for r in cur.fetchall()]
                if not matched:
                    return EmbeddingSearchResponse(results=[])
                if len(matched) <= _PREFILTER_MAX_PAPERS:
                    params["paper_uuids"] = matched

            # hnsw.ef_search has a hard upper bound of 1000 in pgvector;
            # at large n_results, ann_k can exceed that and the SET fails.
            cur.execute("SET LOCAL hnsw.ef_search = %s;", (min(max(ann_k, 200), 1000),))
            cur.execute("SET LOCAL hnsw.iterative_scan = 'relaxed_order';")
            cur.execute("SET LOCAL hnsw.max_scan_tuples = %s;", (_HNSW_MAX_SCAN_TUPLES,))
            shapes = [
                (branch, _estimate_rows(cur, branch, params, params) <= _EXACT_MAX_ROWS)
                for branch in _source_branches(params)
            ]
            cur.execute(_embedding_sql(params, mode, shapes), params)
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
                kind=r["kind"],
                formality=r["formality"],
                body=r["body"],
                slogan=r["slogan"],
                source=r["source"],
                title=r["title"],
                authors=r["authors"] or [],
                url=r["url"],
                external_id=r["external_id"],
                categories=r["categories"] or [],
                year=r["year"],
                journal_ref=r["journal_ref"],
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
