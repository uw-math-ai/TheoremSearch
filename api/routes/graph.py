from typing import Dict, List, Literal, Optional
from fastapi import APIRouter, HTTPException, Query

from db import rds_conn
from models import (
    StatementNode, DependencyEdge, SubgraphResponse,
    IdsRequest, StatementDetail, PaperDetail,
    GraphPaperItem, GraphPaperResponse, PaperItem, StatementItem, DependencyItem,
)

router = APIRouter()


# Maps paper.source → the source's metadata table, the column it keys on
# (always equals paper.external_id), and the fields we surface in PaperItem.
# Fields explicitly excluded per spec: preamble, bibliography, bibtex,
# in_validation, reference_ids, citation_count.
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


def _fetch_slogans(cur, statement_ids: list) -> Dict[str, str]:
    """For each statement_id, return the earliest slogan whose
    ``insufficient_context`` is FALSE. Statements without such a slogan are
    absent from the returned dict.
    """
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
# Graph traversal                                                     #
# ------------------------------------------------------------------ #

def _traverse(cur, start_ids: list, depth: int, direction: str) -> list:
    """Return all statement UUIDs reachable from start_ids within depth hops."""
    if direction == "dependency":
        recursive_sql = (
            "SELECT d.dep_id, t.depth + 1 "
            "FROM traversal t "
            "JOIN informal_dependency d ON d.src_id = t.statement_id "
            "WHERE t.depth < %s AND d.dep_id IS NOT NULL"
        )
        params = (start_ids, depth)
    elif direction == "dependent":
        recursive_sql = (
            "SELECT d.src_id, t.depth + 1 "
            "FROM traversal t "
            "JOIN informal_dependency d ON d.dep_id = t.statement_id "
            "WHERE t.depth < %s"
        )
        params = (start_ids, depth)
    else:  # both
        recursive_sql = (
            "SELECT d.dep_id, t.depth + 1 "
            "FROM traversal t "
            "JOIN informal_dependency d ON d.src_id = t.statement_id "
            "WHERE t.depth < %s AND d.dep_id IS NOT NULL "
            "UNION "
            "SELECT d.src_id, t.depth + 1 "
            "FROM traversal t "
            "JOIN informal_dependency d ON d.dep_id = t.statement_id "
            "WHERE t.depth < %s"
        )
        params = (start_ids, depth, depth)

    cur.execute(
        f"""
        WITH RECURSIVE traversal(statement_id, depth) AS (
            SELECT s.statement_id, 0
            FROM statement s
            WHERE s.statement_id = ANY(%s::uuid[])
            UNION
            {recursive_sql}
        )
        SELECT statement_id, MIN(depth) FROM traversal GROUP BY statement_id
        """,
        params,
    )
    return {row[0]: row[1] for row in cur.fetchall()}


def _build_subgraph(cur, node_depth: dict) -> SubgraphResponse:
    node_ids = list(node_depth.keys())
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
    depth: int = Query(default=1, ge=1, le=10),
    direction: Literal["dependency", "dependent", "both"] = "dependency",
):
    with rds_conn("v2") as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM statement WHERE statement_id = %s", (statement_id,))
        if cur.fetchone() is None:
            raise HTTPException(status_code=404, detail=f"No statement with id '{statement_id}'")
        node_depth = _traverse(cur, [statement_id], depth, direction)
        return _build_subgraph(cur, node_depth)


def _fetch_paper_item(cur, paper_id: str, minimal: bool) -> PaperItem:
    """Look up a paper plus its source-specific metadata. Raises 404."""
    if minimal:
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


def _fetch_paper_statements(cur, paper_id: str, minimal: bool) -> List[StatementItem]:
    if minimal:
        cur.execute(
            """
            SELECT s.statement_id, s.kind, im.ref
            FROM statement s
            LEFT JOIN informal_metadata im ON im.statement_id = s.statement_id
            WHERE s.paper_id = %s AND s.formality = 'informal'
            ORDER BY im.ordinal
            """,
            (paper_id,),
        )
        return [
            StatementItem(
                statement_id=str(r[0]),
                name=r[1].capitalize() + (f" {r[2]}" if r[2] else ""),
            )
            for r in cur.fetchall()
        ]

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


def _fetch_formal_statements(cur, paper_id: str, minimal: bool) -> List[StatementItem]:
    """Formal counterpart of _fetch_paper_statements. The 'name' for a formal
    statement is its Lean fully-qualified ``decl_name`` (e.g.
    ``AddDissociated.boringEnergy_le``). Statements missing a decl_name fall
    back to a synthetic placeholder so the required ``name`` field stays set."""
    def _name(decl_name: str | None, sid) -> str:
        return decl_name or f"<unnamed {str(sid)[:8]}>"

    if minimal:
        cur.execute(
            """
            SELECT s.statement_id, fm.decl_name
            FROM statement s
            JOIN formal_metadata fm ON fm.statement_id = s.statement_id
            WHERE s.paper_id = %s AND s.formality = 'formal'
            ORDER BY fm.decl_name
            """,
            (paper_id,),
        )
        return [
            StatementItem(statement_id=str(r[0]), name=_name(r[1], r[0]))
            for r in cur.fetchall()
        ]

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
            body=r[3],            # signature
            proof=r[4],            # tactic_summary (usually NULL today)
            slogan=slogans.get(str(r[0])),
            docstring=r[8],
            module=r[6],
            file_path=r[7],
        )
        for r in rows
    ]


def _fetch_paper_dependencies(cur, paper_id: str, minimal: bool) -> List[DependencyItem]:
    # Same row filter the older /graph endpoint uses: drop unresolved interpaper
    # citations (cite_key set but no cite_id) — those are dangling edges.
    if minimal:
        cur.execute(
            """
            SELECT d.src_id, d.cite_id, d.dep_id
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


def _fetch_formal_dependencies(cur, paper_id: str, minimal: bool) -> List[DependencyItem]:
    """Formal counterpart of _fetch_paper_dependencies, pulling from
    formal_dependency. Note: src AND dep are both UUIDs (no cite_id concept,
    since formal deps are always intra-corpus and resolved)."""
    if minimal:
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
    cur, paper_id: str, items: List[GraphPaperItem], minimal: bool,
) -> GraphPaperResponse:
    chosen = set(items)

    # Single look-up handles existence + routing: lean_repo → formal pipeline,
    # anything else → the informal pipeline.
    cur.execute("SELECT kind FROM paper WHERE paper_id = %s", (paper_id,))
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No paper with id '{paper_id}'")
    is_formal = row[0] == "lean_repo"

    paper = _fetch_paper_item(cur, paper_id, minimal) if "paper" in chosen else None
    statements_fn   = _fetch_formal_statements   if is_formal else _fetch_paper_statements
    dependencies_fn = _fetch_formal_dependencies if is_formal else _fetch_paper_dependencies
    return GraphPaperResponse(
        paper=paper,
        statements=statements_fn(cur, paper_id, minimal) if "statements" in chosen else None,
        dependencies=dependencies_fn(cur, paper_id, minimal) if "dependencies" in chosen else None,
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
    minimal: bool = Query(
        default=False,
        description="Return only the minimal fields per item (paper=paper_id+title; "
                    "statements=statement_id+name; dependencies=src_id+cite_id+dep_id).",
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
        return _graph_paper_response(cur, str(row[0]), items or _ALL_ITEMS, minimal)


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
    minimal: bool = Query(
        default=False,
        description="Return only the minimal fields per item (paper=paper_id+title; "
                    "statements=statement_id+name; dependencies=src_id+cite_id+dep_id).",
    ),
):
    with rds_conn("v2") as conn, conn.cursor() as cur:
        return _graph_paper_response(cur, paper_id, items or _ALL_ITEMS, minimal)


# ------------------------------------------------------------------ #
# Hydration — single                                                  #
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


# ------------------------------------------------------------------ #
# Hydration — batch                                                   #
# ------------------------------------------------------------------ #

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
