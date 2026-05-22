"""Graph navigation under /graph.

Three subroutes:
  - /graph/paper        : find a paper (by id or by source+external_id) plus
                          its statements and dependencies.
  - /graph/statement    : center the graph at a statement and traverse out.
  - /graph/embedding    : semantic search via slogan embeddings.
"""
import os
from typing import Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query
from openai import OpenAI

from db import rds_conn
from models import (
    StatementNode, DependencyEdge, SubgraphResponse,
    IdsRequest, StatementDetail, PaperDetail,
    GraphPaperItem, GraphPaperResponse, PaperItem, StatementItem, DependencyItem,
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

_ALL_ITEMS: List[GraphPaperItem] = ["paper", "statements", "dependencies"]

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
    depth: int,
    direction: Direction,
    formality: Formality,
) -> Dict[str, int]:
    """All reachable statements within `depth` hops, with their BFS depth."""
    dep_table = "formal_dependency" if formality == "formal" else "informal_dependency"
    # informal_dependency.dep_id can be NULL (unresolved cites); formal can't.
    out_filter = "" if formality == "formal" else "AND d.dep_id IS NOT NULL"

    out_sql = (
        f"SELECT d.dep_id, t.depth + 1 "
        f"FROM traversal t "
        f"JOIN {dep_table} d ON d.src_id = t.statement_id "
        f"WHERE t.depth < %s {out_filter}"
    )
    in_sql = (
        f"SELECT d.src_id, t.depth + 1 "
        f"FROM traversal t "
        f"JOIN {dep_table} d ON d.dep_id = t.statement_id "
        f"WHERE t.depth < %s"
    )

    if direction == "src":
        recursive_sql, params = out_sql, (start_ids, depth)
    elif direction == "dep":
        recursive_sql, params = in_sql, (start_ids, depth)
    else:
        recursive_sql, params = f"{out_sql} UNION {in_sql}", (start_ids, depth, depth)

    cur.execute(
        f"""
        WITH RECURSIVE traversal(statement_id, depth) AS (
            SELECT s.statement_id, 0
            FROM statement s
            WHERE s.statement_id = ANY(%s::uuid[])
            UNION ALL
            {recursive_sql}
        )
        SELECT statement_id, MIN(depth) FROM traversal GROUP BY statement_id
        """,
        params,
    )
    return {row[0]: row[1] for row in cur.fetchall()}


def _build_subgraph(
    cur,
    node_depth: Dict,
    formality: Formality,
) -> SubgraphResponse:
    node_ids = list(node_depth.keys())

    if formality == "formal":
        cur.execute(
            """
            SELECT s.statement_id, s.kind, fm.decl_name
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
                name=r[2] or f"<unnamed {str(r[0])[:8]}>",
                slogan=slogans.get(str(r[0])),
                depth=node_depth[r[0]],
            )
            for r in stmt_rows
        ]

        cur.execute(
            """
            SELECT src_id, dep_id, edge_type
            FROM formal_dependency
            WHERE src_id = ANY(%s::uuid[])
            """,
            (node_ids,),
        )
        edges = [
            DependencyEdge(
                src_id=str(r[0]),
                dep_id=str(r[1]),
                edge_type=r[2],
            )
            for r in cur.fetchall()
        ]
        return SubgraphResponse(nodes=nodes, edges=edges)

    # informal
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
            depth=node_depth[r[0]],
        )
        for r in stmt_rows
    ]

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


@router.get("/graph/statement/{statement_id}", response_model=SubgraphResponse)
async def graph_statement(
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
):
    with rds_conn("v2") as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM statement WHERE statement_id = %s", (statement_id,))
        if cur.fetchone() is None:
            raise HTTPException(status_code=404, detail=f"No statement with id '{statement_id}'")
        node_depth = _traverse(cur, [statement_id], 1, direction, formality)
        return _build_subgraph(cur, node_depth, formality)


# ------------------------------------------------------------------ #
# /graph/paper                                                        #
# ------------------------------------------------------------------ #

def _fetch_paper_item(cur, paper_id: str) -> PaperItem:
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


def _fetch_informal_statements(cur, paper_id: str) -> List[StatementItem]:
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


def _fetch_formal_statements(cur, paper_id: str) -> List[StatementItem]:
    def _name(decl_name: Optional[str], sid) -> str:
        return decl_name or f"<unnamed {str(sid)[:8]}>"

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


def _fetch_informal_dependencies(cur, paper_id: str) -> List[DependencyItem]:
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


def _fetch_formal_dependencies(cur, paper_id: str) -> List[DependencyItem]:
    cur.execute(
        """
        SELECT d.src_id, d.dep_id, d.edge_type
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
            edge_type=r[2],
        )
        for r in cur.fetchall()
    ]


def _graph_paper_response(
    cur, paper_id: str, items: List[GraphPaperItem],
) -> GraphPaperResponse:
    chosen = set(items)
    cur.execute("SELECT kind FROM paper WHERE paper_id = %s", (paper_id,))
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No paper with id '{paper_id}'")
    is_formal = row[0] == "lean_repo"

    paper = _fetch_paper_item(cur, paper_id) if "paper" in chosen else None
    statements_fn   = _fetch_formal_statements   if is_formal else _fetch_informal_statements
    dependencies_fn = _fetch_formal_dependencies if is_formal else _fetch_informal_dependencies
    return GraphPaperResponse(
        paper=paper,
        statements=statements_fn(cur, paper_id) if "statements" in chosen else None,
        dependencies=dependencies_fn(cur, paper_id) if "dependencies" in chosen else None,
    )


@router.get(
    "/graph/paper",
    response_model=GraphPaperResponse,
    response_model_exclude_none=True,
)
async def graph_paper_by_source(
    source: str = Query(..., description="paper.source, e.g. 'arXiv' or 'Lean Community'"),
    external_id: str = Query(..., description="paper.external_id within that source"),
    items: Optional[List[GraphPaperItem]] = Query(
        default=None,
        description="Which top-level keys to populate. Defaults to all three.",
    ),
):
    with rds_conn("v2") as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT paper_id FROM paper WHERE source = %s AND external_id = %s",
            (source, external_id),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"No paper with source={source!r} external_id={external_id!r}",
            )
        return _graph_paper_response(cur, str(row[0]), items or _ALL_ITEMS)


@router.get(
    "/graph/paper/{paper_id}",
    response_model=GraphPaperResponse,
    response_model_exclude_none=True,
)
async def graph_paper(
    paper_id: str,
    items: Optional[List[GraphPaperItem]] = Query(
        default=None,
        description="Which top-level keys to populate. Defaults to all three.",
    ),
):
    with rds_conn("v2") as conn, conn.cursor() as cur:
        return _graph_paper_response(cur, paper_id, items or _ALL_ITEMS)


# ------------------------------------------------------------------ #
# /graph/embedding — semantic search                                  #
# ------------------------------------------------------------------ #

_EMBED_MODEL = "qwen3-8b"
_QUERY_INSTRUCTION = "Given a math search query, retrieve theorems mathematically equivalent to the query.\n"
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
    provider_model, _ = _embed_model_info(_EMBED_MODEL)
    resp = _embed_client().embeddings.create(
        model=provider_model,
        input=_QUERY_INSTRUCTION + query,
        encoding_format="float",
    )
    return resp.data[0].embedding


# Two-stage: binary-quantized HNSW narrows candidates by Hamming distance,
# then full-precision cosine reranks.
_EMBEDDING_SQL = """
WITH ann AS (
    SELECT e.slogan_id, e.embedding
    FROM embedding e
    JOIN slogan s ON s.slogan_id = e.slogan_id
    WHERE e.model_name = %(model)s
      AND s.model_name = ANY(%(slogan_models)s)
    ORDER BY
        binary_quantize(e.embedding)::bit(4096)
        <~>
        binary_quantize(%(q)s::vector(4096))::bit(4096)
    LIMIT %(ann_k)s
),
ranked AS (
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
        1.0 - (ann.embedding <=> %(q)s::vector(4096)) AS similarity
    FROM ann
    JOIN slogan s     ON s.slogan_id = ann.slogan_id
    JOIN statement st ON st.statement_id = s.statement_id
    JOIN paper p      ON p.paper_id = st.paper_id
    LEFT JOIN informal_metadata im     ON im.statement_id = st.statement_id
    LEFT JOIN arxiv_paper_metadata apm ON apm.arxiv_id = p.external_id
    WHERE NOT s.insufficient_context
      AND (%(sources)s::text[] IS NULL OR p.source = ANY(%(sources)s))
      AND (%(types)s::text[]   IS NULL OR LOWER(st.kind) = ANY(%(types)s))
      AND (%(author_patterns)s::text[] IS NULL OR EXISTS (
              SELECT 1 FROM unnest(p.authors) a
              WHERE LOWER(a) LIKE ANY(%(author_patterns)s)
      ))
      AND COALESCE(apm.citation_count, 0) >= %(min_citations)s
      AND (%(in_journal)s::boolean IS NULL
           OR (apm.journal_ref IS NOT NULL) = %(in_journal)s)
    ORDER BY ann.embedding <=> %(q)s::vector(4096)
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


@router.get("/graph/embedding", response_model=EmbeddingSearchResponse)
async def graph_embedding(
    query: str = Query(..., min_length=1, description="Natural-language search query."),
    n_results: int = Query(10, ge=1, le=100),
    sources: List[str] = Query(default=[], description="Paper sources, e.g. 'arXiv'."),
    types: List[str] = Query(default=[], description="Statement kinds, e.g. theorem, lemma."),
    authors: List[str] = Query(default=[], description="Author substring filter."),
    min_citations: int = Query(0, ge=0),
    citation_weight: float = Query(0.0, ge=0.0),
    in_journal: Optional[bool] = Query(None),
):
    try:
        query_vec = _embed_query(query)
        top_k = n_results * 5
        ann_k = max(top_k * 4, 200)

        params = {
            "q":               query_vec,
            "model":           _EMBED_MODEL,
            "slogan_models":   _SLOGAN_MODELS,
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

        with rds_conn("v2") as conn, conn.cursor() as cur:
            cur.execute("SET LOCAL hnsw.ef_search = %s;", (max(ann_k, 200),))
            cur.execute("SET LOCAL hnsw.iterative_scan = 'relaxed_order';")
            cur.execute(_EMBEDDING_SQL, params)
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]

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
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"/graph/embedding failed: {str(e)}")


# ------------------------------------------------------------------ #
# Hydration (single + batch) — not graph navigation; kept at root.    #
# ------------------------------------------------------------------ #

@router.get("/statement/{statement_id}", response_model=StatementDetail)
async def get_statement(statement_id: str):
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
async def get_paper(paper_id: str):
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
async def batch_statements(body: IdsRequest):
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
async def batch_papers(body: IdsRequest):
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
async def list_papers():
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
