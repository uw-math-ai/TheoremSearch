from fastapi import APIRouter, Query
from typing import List

from db import rds_conn

router = APIRouter()


@router.get("/paper-search")
async def paper_search(q: str = "", limit: int = 8):
    """Autocomplete: search all papers by title or external_id."""
    if not q.strip():
        return {"papers": []}
    with rds_conn("v2") as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT paper_id, title, external_id, source
            FROM paper
            WHERE title ILIKE %s OR external_id ILIKE %s
            ORDER BY
                CASE WHEN external_id ILIKE %s THEN 0 ELSE 1 END,
                title
            LIMIT %s
            """,
            (f"%{q}%", f"%{q}%", f"{q}%", limit),
        )
        rows = cur.fetchall()
    return {
        "papers": [
            {
                "paper_id": str(r[0]),
                "title": r[1],
                "external_id": r[2],
                "source": r[3],
            }
            for r in rows
        ]
    }


@router.get("/paper-resolve")
async def paper_resolve(external_id: List[str] = Query(default=[])):
    """Resolve a list of external_ids to paper info (used by JSON graph mode)."""
    if not external_id:
        return {"papers": []}
    with rds_conn("v2") as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT paper_id, title, external_id, source
            FROM paper
            WHERE external_id = ANY(%s)
            """,
            (external_id,),
        )
        rows = cur.fetchall()
    return {
        "papers": [
            {
                "paper_id": str(r[0]),
                "title": r[1],
                "external_id": r[2],
                "source": r[3],
            }
            for r in rows
        ]
    }
