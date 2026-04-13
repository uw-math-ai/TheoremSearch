from typing import List
from fastapi import APIRouter, HTTPException

from db import rds_conn
from models import (
    StatementNode, DependencyEdge, GraphResponse,
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
                   d.dep_name, d.dep_key, d.location, d.method
            FROM informal_dependency d
            JOIN statement s ON s.statement_id = d.src_id
            WHERE s.paper_id = %s
              AND (d.cite_key IS NULL OR d.cite_id IS NOT NULL)
            """,
            (paper_id,),
        )
        dep_rows = cur.fetchall()

    statements = [
        StatementNode(statement_id=str(sid), kind=kind, ref=ref)
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
            method=method,
        )
        for src_id, dep_id, cite_id, cite_key, dep_name, dep_key, location, method in dep_rows
    ]

    return GraphResponse(
        paper_id=str(paper_id),
        statements=statements,
        dependencies=dependencies,
    )


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


# ------------------------------------------------------------------ #
# Paper-level utilities                                               #
# ------------------------------------------------------------------ #

@router.get("/paper-links")
async def paper_links():
    """Return all directed citation edges among the galaxy papers (ag_papers_100)."""
    with rds_conn("v2") as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT sp.paper_id AS src, d.cite_id AS tgt
            FROM informal_dependency d
            JOIN statement s  ON s.statement_id = d.src_id
            JOIN paper sp     ON sp.paper_id     = s.paper_id
            WHERE d.cite_key IS NOT NULL
              AND d.cite_id IS NOT NULL
              AND sp.paper_id IN (SELECT paper_id FROM ag_papers_100)
              AND d.cite_id   IN (SELECT paper_id FROM ag_papers_100)
            """
        )
        rows = cur.fetchall()
    return {"links": [{"source": str(r[0]), "target": str(r[1])} for r in rows]}


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
