from collections import defaultdict
from typing import List

from rds.utils.upsert import upsert_rows
from .match import match_paper

def _write_paper_deps(conn, all_statement_ids: List[str], statements_with_extracts: List[dict]) -> int:
    statements = statements_with_extracts
    dep_rows   = match_paper(statements)

    seen_notation: set = set()
    notation_rows = []
    for s in statements:
        for d in s.get("defines", []):
            if not d.get("pattern") or not d.get("description"):
                continue
            key = (s["statement_id"], d["pattern"])
            if key in seen_notation:
                continue
            seen_notation.add(key)
            notation_rows.append({
                "statement_id": s["statement_id"],
                "pattern":      d["pattern"],
                "description":  d["description"],
            })

    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM informal_dependency"
            " WHERE src_id = ANY(%s::uuid[]) AND method = 'llm' AND cite_key IS NULL",
            (all_statement_ids,),
        )
        cur.execute(
            "DELETE FROM notation WHERE statement_id = ANY(%s::uuid[])",
            (all_statement_ids,),
        )
        if dep_rows:
            upsert_rows(conn, "informal_dependency", dep_rows)
        if notation_rows:
            upsert_rows(conn, "notation", notation_rows)
    conn.commit()
    return len(dep_rows), len(notation_rows)


def _fetch_paper_statements(conn, paper_ids: List[str]) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.statement_id, s.paper_id, s.kind, im.note, s.body, s.proof,
                   im.ordinal
            FROM statement s
            JOIN informal_metadata im ON im.statement_id = s.statement_id
            WHERE s.paper_id = ANY(%s::uuid[])
            ORDER BY s.paper_id, im.ordinal
            """,
            (paper_ids,),
        )
        rows = cur.fetchall()
    stmts_by_paper: dict = defaultdict(list)
    for row in rows:
        d = dict(zip(["statement_id", "paper_id", "kind", "note", "body", "proof", "ordinal"], row))
        d["statement_id"] = str(d["statement_id"])
        d["paper_id"]     = str(d["paper_id"])
        stmts_by_paper[d["paper_id"]].append(d)
    return stmts_by_paper


def _papers_already_processed(conn, paper_ids: List[str]) -> set:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT s.paper_id::text
            FROM informal_dependency d
            JOIN statement s ON s.statement_id = d.src_id
            WHERE s.paper_id = ANY(%s::uuid[])
              AND d.method = 'llm' AND d.cite_key IS NULL
            """,
            (paper_ids,),
        )
        return {row[0] for row in cur.fetchall()}
