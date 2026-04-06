from fastapi import APIRouter, HTTPException, Query

from db import rds_conn
from models import PaperNode, DependencyEdge, GraphResponse

router = APIRouter()

MAX_DEPTH = 5


@router.get("/graph", response_model=GraphResponse)
async def graph(external_id: str, depth: int = Query(default=1, ge=1, le=MAX_DEPTH)):
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

        # Recursively expand the source frontier depth-1 levels into external papers,
        # then fetch all dependency edges whose source is in that frontier.
        cur.execute(
            """
            WITH RECURSIVE src_frontier(statement_id, lvl) AS (
                SELECT s.statement_id, 0
                FROM statement s
                WHERE s.paper_id = %s

                UNION

                SELECT d.dep_id, f.lvl + 1
                FROM src_frontier f
                JOIN dependency d ON d.source_id = f.statement_id
                WHERE d.dep_id IS NOT NULL
                  AND f.lvl < %s - 1
            )
            SELECT
                d.interpaper,
                d.cite_key,
                d.dep_key,
                ss.statement_id                       AS src_statement_id,
                ss.kind                               AS src_kind,
                ss.body                               AS src_body,
                ss.proof                              AS src_proof,
                sim.ref                               AS src_ref,
                sim.note                              AS src_note,
                sp.paper_id                           AS src_paper_id,
                sp.external_id                        AS src_paper_ext_id,
                sp.title                              AS src_paper_title,
                ds.statement_id                       AS dep_statement_id,
                ds.kind                               AS dep_kind,
                ds.body                               AS dep_body,
                dim.ref                               AS dep_ref,
                COALESCE(ds.paper_id, d.cite_id)      AS dep_paper_id,
                COALESCE(dp.external_id, cp.external_id) AS dep_paper_ext_id,
                COALESCE(dp.title,       cp.title)    AS dep_paper_title
            FROM src_frontier f
            JOIN dependency d   ON d.source_id    = f.statement_id
            JOIN statement ss   ON ss.statement_id = d.source_id
            JOIN paper sp       ON sp.paper_id     = ss.paper_id
            LEFT JOIN informal_metadata sim ON sim.statement_id = d.source_id
            LEFT JOIN statement         ds  ON ds.statement_id  = d.dep_id
            LEFT JOIN informal_metadata dim ON dim.statement_id = d.dep_id
            LEFT JOIN paper             dp  ON dp.paper_id      = ds.paper_id
            LEFT JOIN paper             cp  ON cp.paper_id      = d.cite_id
            """,
            (paper_id, depth),
        )
        rows = cur.fetchall()

    edges = []
    for row in rows:
        (
            interpaper, cite_key, dep_key,
            src_statement_id, src_kind, src_body, src_proof, src_ref, src_note,
            src_paper_id, src_paper_ext_id, src_paper_title,
            dep_statement_id, dep_kind, dep_body, dep_ref,
            dep_paper_id, dep_paper_ext_id, dep_paper_title,
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
            src_paper_id=str(src_paper_id),
            src_paper_ext_id=src_paper_ext_id,
            src_paper_title=src_paper_title,
            dep_statement_id=str(dep_statement_id) if dep_statement_id is not None else None,
            dep_name=dep_name,
            dep_body=dep_body,
            dep_key=dep_key,
            dep_paper_id=str(dep_paper_id) if dep_paper_id is not None else None,
            dep_paper_ext_id=dep_paper_ext_id,
            dep_paper_title=dep_paper_title,
            cited_paper_key=cite_key,
            interpaper=interpaper,
        ))

    return GraphResponse(paper=paper, dependencies=edges)


@router.get("/paper-links")
async def paper_links():
    """Return all directed citation edges among the galaxy papers (ag_papers_100)."""
    with rds_conn("v2") as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT sp.paper_id AS src, d.cite_id AS tgt
            FROM dependency d
            JOIN statement s  ON s.statement_id = d.source_id
            JOIN paper sp     ON sp.paper_id     = s.paper_id
            WHERE d.interpaper IS TRUE
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
            SELECT paper_id, title, external_id, source, url
            FROM ag_papers_100
            ORDER BY title
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
            }
            for r in rows
        ]
    }
