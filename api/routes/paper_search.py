from fastapi import APIRouter

from db import rds_conn

router = APIRouter()


@router.get("/paper-search")
def paper_search(q: str = "", limit: int = 8):
    """Autocomplete: search all papers by title or external_id."""
    q = q.strip()
    if not q:
        return {"papers": []}

    with rds_conn("v2") as conn, conn.cursor() as cur:
        # 1. Exact-prefix match on external_id — uses idx_paper_external_id_lower_prefix
        cur.execute(
            """
            SELECT paper_id, title, external_id, source
            FROM paper
            WHERE lower(external_id) LIKE lower(%s)
            ORDER BY external_id
            LIMIT %s
            """,
            (f"{q}%", limit),
        )
        ext_rows = cur.fetchall()

        # 2. Trigram match on title — uses idx_paper_title_trgm
        cur.execute(
            """
            SELECT paper_id, title, external_id, source
            FROM paper
            WHERE LOWER(title) LIKE %s
            ORDER BY title
            LIMIT %s
            """,
            (f"%{q.lower()}%", limit),
        )
        title_rows = cur.fetchall()

    # Merge: external_id prefix matches first, then title matches, deduplicated
    seen: set = set()
    papers = []
    for row in ext_rows + title_rows:
        if row[0] not in seen:
            seen.add(row[0])
            papers.append({
                "paper_id": str(row[0]),
                "title": row[1],
                "external_id": row[2],
                "source": row[3],
            })
        if len(papers) >= limit:
            break

    return {"papers": papers}

