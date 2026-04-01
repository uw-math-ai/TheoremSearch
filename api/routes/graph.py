from fastapi import APIRouter, HTTPException

from db import rds_conn
from models import StatementNode, PaperNode, DependencyEdge, GraphResponse

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
                d.kind,
                d.interpaper,
                d.dep_name,
                d.dep_key,
                d.cite_key,
                d.tactic_context,
                ss.statement_id  AS src_id,
                ss.formality     AS src_formality,
                ss.kind          AS src_kind,
                ss.body          AS src_body,
                sim.ref          AS src_ref,
                sim.label        AS src_label,
                sfm.decl_name    AS src_decl_name,
                ds.statement_id  AS dep_id,
                ds.formality     AS dep_formality,
                ds.kind          AS dep_kind,
                ds.body          AS dep_body,
                dim.ref          AS dep_ref,
                dim.label        AS dep_label,
                dfm.decl_name    AS dep_decl_name,
                dp.paper_id      AS dep_paper_id,
                dp.title         AS dep_paper_title,
                dp.external_id   AS dep_paper_ext_id,
                dp.source        AS dep_paper_source,
                dp.url           AS dep_paper_url
            FROM dependency d
            JOIN statement ss ON ss.statement_id = d.source_id
            LEFT JOIN informal_metadata sim ON sim.statement_id = d.source_id
            LEFT JOIN formal_metadata   sfm ON sfm.statement_id = d.source_id
            LEFT JOIN statement         ds  ON ds.statement_id  = d.dep_id
            LEFT JOIN informal_metadata dim ON dim.statement_id = d.dep_id
            LEFT JOIN formal_metadata   dfm ON dfm.statement_id = d.dep_id
            LEFT JOIN paper             dp  ON dp.paper_id      = ds.paper_id
            WHERE ss.paper_id = %s
            """,
            (paper_id,),
        )
        rows = cur.fetchall()

    edges = []
    for row in rows:
        (
            kind, interpaper, dep_name, dep_key, cite_key, tactic_context,
            src_id, src_formality, src_kind, src_body, src_ref, src_label, src_decl,
            dep_sid, dep_formality, dep_kind, dep_body, dep_ref, dep_label, dep_decl,
            dep_paper_id, dep_paper_title, dep_paper_ext_id, dep_paper_source, dep_paper_url,
        ) = row

        source_node = StatementNode(
            statement_id=str(src_id),
            formality=src_formality,
            kind=src_kind,
            body=src_body,
            ref=src_ref,
            label=src_label,
            decl_name=src_decl,
        )

        dep_node = None
        if dep_sid is not None:
            dep_node = StatementNode(
                statement_id=str(dep_sid),
                formality=dep_formality,
                kind=dep_kind,
                body=dep_body,
                ref=dep_ref,
                label=dep_label,
                decl_name=dep_decl,
            )

        dep_paper_node = None
        if dep_paper_id is not None:
            dep_paper_node = PaperNode(
                paper_id=str(dep_paper_id),
                title=dep_paper_title,
                external_id=dep_paper_ext_id,
                source=dep_paper_source,
                url=dep_paper_url,
            )

        edges.append(DependencyEdge(
            kind=kind,
            interpaper=interpaper,
            dep_name=dep_name,
            dep_key=dep_key,
            cite_key=cite_key,
            tactic_context=tactic_context,
            source=source_node,
            dep=dep_node,
            dep_paper=dep_paper_node,
        ))

    return GraphResponse(paper=paper, dependencies=edges)
