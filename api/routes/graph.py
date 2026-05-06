from typing import List, Literal
from fastapi import APIRouter, HTTPException, Query

from db import rds_conn
from models import (
    StatementNode, DependencyEdge, GraphResponse, SubgraphResponse,
    IdsRequest, StatementDetail, PaperDetail,
)

router = APIRouter()


@router.get("/graph", response_model=GraphResponse)
async def graph(external_id: str):
    with rds_conn("v2") as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT paper_id FROM paper WHERE external_id = %s AND kind = 'paper'",
            (external_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"No paper found with external_id '{external_id}'",
            )
        paper_id = row[0]

        cur.execute(
            """
            SELECT s.statement_id, s.kind, im.ref
            FROM statement s
            LEFT JOIN informal_metadata im ON im.statement_id = s.statement_id
            WHERE s.paper_id = %s
            """,
            (paper_id,),
        )
        stmt_rows = cur.fetchall()

        # Interpaper deps only included when cite_id is resolved.
        cur.execute(
            """
            SELECT d.src_id, d.dep_id, d.cite_id, d.cite_key,
                   d.dep_name, d.dep_key, d.location, d.methods
            FROM informal_dependency d
            JOIN statement s ON s.statement_id = d.src_id
            WHERE s.paper_id = %s
              AND (d.cite_key IS NULL OR d.cite_id IS NOT NULL)
            """,
            (paper_id,),
        )
        dep_rows = cur.fetchall()

    statements = [
        StatementNode(
            statement_id=str(sid),
            name=kind.capitalize() + (f" {ref}" if ref else ""),
        )
        for sid, kind, ref in stmt_rows
    ]

    dependencies = [
        DependencyEdge(
            src_id=str(src_id),
            dep_id=str(dep_id) if dep_id is not None else None,
            cite_id=str(cite_id) if cite_id is not None else None,
            cite_key=cite_key,
            dep_name=dep_name,
            dep_key=dep_key,
            location=location,
            methods=methods,
        )
        for src_id, dep_id, cite_id, cite_key, dep_name, dep_key, location, methods in dep_rows
    ]

    return GraphResponse(
        paper_id=str(paper_id),
        statements=statements,
        dependencies=dependencies,
    )


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
    nodes = [
        StatementNode(
            statement_id=str(r[0]),
            name=r[1].capitalize() + (f" {r[2]}" if r[2] else ""),
            depth=node_depth[r[0]],
        )
        for r in cur.fetchall()
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


@router.get("/graph/paper/{paper_id}", response_model=SubgraphResponse)
async def graph_paper(
    paper_id: str,
    depth: int = Query(default=1, ge=1, le=10),
    direction: Literal["dependency", "dependent", "both"] = "dependency",
):
    with rds_conn("v2") as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT statement_id FROM statement WHERE paper_id = %s",
            (paper_id,),
        )
        rows = cur.fetchall()
        if not rows:
            raise HTTPException(status_code=404, detail=f"No paper with id '{paper_id}' or paper has no statements")
        start_ids = [str(r[0]) for r in rows]
        node_depth = _traverse(cur, start_ids, depth, direction)
        return _build_subgraph(cur, node_depth)


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
