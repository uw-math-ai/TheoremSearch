from fastapi import APIRouter, HTTPException

from db import rds_conn
from models import PaperNode, DependencyEdge, GraphResponse

router = APIRouter()


@router.get("/graph", response_model=GraphResponse)
async def graph(external_id: str):
    with rds_conn("v2") as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT paper_id, title, external_id, source, url
            FROM paper
            WHERE external_id = %s
            """,
            (external_id,),
        )
        paper_row = cur.fetchone()
        if paper_row is None:
            raise HTTPException(
                status_code=404,
                detail=f"No paper found with external_id '{external_id}'",
            )

        paper_id, title, ext_id, source, url = paper_row
        paper = PaperNode(
            paper_id=str(paper_id),
            title=title,
            external_id=ext_id,
            source=source,
            url=url,
        )

        cur.execute(
            """
            SELECT
                d.interpaper,
                d.cite_key,
                d.dep_key,
                ss.statement_id  AS src_statement_id,
                ss.kind          AS src_kind,
                ss.body          AS src_body,
                ss.proof         AS src_proof,
                sim.ref          AS src_ref,
                sim.note         AS src_note,
                ds.statement_id  AS dep_statement_id,
                ds.kind          AS dep_kind,
                ds.body          AS dep_body,
                dim.ref          AS dep_ref,
                dp.external_id   AS dep_paper_ext_id
            FROM dependency d
            JOIN statement ss ON ss.statement_id = d.source_id
            LEFT JOIN informal_metadata sim ON sim.statement_id = d.source_id
            LEFT JOIN statement         ds  ON ds.statement_id  = d.dep_id
            LEFT JOIN informal_metadata dim ON dim.statement_id = d.dep_id
            LEFT JOIN paper             dp  ON dp.paper_id      = ds.paper_id
            WHERE ss.paper_id = %s
            """,
            (paper_id,),
        )
        rows = cur.fetchall()

    edges = []
    for row in rows:
        (
            interpaper, cite_key, dep_key,
            src_statement_id, src_kind, src_body, src_proof, src_ref, src_note,
            dep_statement_id, dep_kind, dep_body, dep_ref,
            dep_paper_ext_id,
        ) = row

        src_name = f"{src_kind.capitalize()} {src_ref}" if src_ref else src_kind.capitalize()

        dep_name = None
        if dep_kind is not None:
            dep_name = f"{dep_kind.capitalize()} {dep_ref}" if dep_ref else dep_kind.capitalize()

        edges.append(DependencyEdge(
            src_statement_id=str(src_statement_id),
            src_name=src_name,
            src_body=src_body,
            src_note=src_note,
            src_proof=src_proof,
            dep_statement_id=str(dep_statement_id) if dep_statement_id is not None else None,
            dep_name=dep_name,
            dep_body=dep_body,
            dep_key=dep_key,
            cited_arxiv_id=dep_paper_ext_id,
            cited_paper_key=cite_key,
            interpaper=interpaper,
        ))

    return GraphResponse(paper=paper, dependencies=edges)
