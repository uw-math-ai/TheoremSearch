from collections import defaultdict
from typing import List

from rds.utils.upsert import upsert_rows


def _method_priority(alias: str) -> str:
    return (
        f"(CASE WHEN {alias}.methods && ARRAY['deterministic'] THEN 4"
        f"      WHEN {alias}.methods && ARRAY['heuristic']     THEN 3"
        f"      WHEN {alias}.methods && ARRAY['llm']           THEN 2"
        f"      WHEN {alias}.methods && ARRAY['judge']         THEN 1 ELSE 0 END)"
    )


def informal_dep_update_expr() -> str:
    """Evidence precedence: deterministic > heuristic > llm > judge.
    dep_key and location are overwritten only when the incoming method has
    strictly higher priority than the best method already on the row.
    methods is always merged (union, no duplicates).
    """
    higher = f"{_method_priority('EXCLUDED')} > {_method_priority('informal_dependency')}"
    return (
        f"dep_key  = CASE WHEN {higher} THEN EXCLUDED.dep_key  ELSE informal_dependency.dep_key  END,"
        f" location = CASE WHEN {higher} THEN EXCLUDED.location ELSE informal_dependency.location END,"
        " methods  = ARRAY(SELECT DISTINCT unnest(informal_dependency.methods || EXCLUDED.methods))"
    )
from .match import match_paper


def _write_paper_deps(conn, all_statement_ids: List[str], statements_with_extracts: List[dict]) -> tuple:
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
        # Strip 'llm' from every intrapaper dep for these statements, then drop
        # rows whose methods array becomes empty. The upsert below re-adds 'llm'
        # for deps the current LLM run still produces.
        cur.execute(
            "UPDATE informal_dependency"
            " SET methods = array_remove(methods, 'llm')"
            " WHERE src_id = ANY(%s::uuid[]) AND cite_key IS NULL AND 'llm' = ANY(methods)",
            (all_statement_ids,),
        )
        cur.execute(
            "DELETE FROM informal_dependency"
            " WHERE src_id = ANY(%s::uuid[]) AND cite_key IS NULL AND cardinality(methods) = 0",
            (all_statement_ids,),
        )
        cur.execute(
            "DELETE FROM notation WHERE statement_id = ANY(%s::uuid[])",
            (all_statement_ids,),
        )
        if dep_rows:
            upsert_rows(conn, "informal_dependency", dep_rows,
                        on_conflict={"with": ["src_id", "dep_id"],
                                     "where": "dep_id IS NOT NULL",
                                     "update_expr": informal_dep_update_expr()})
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
              AND 'llm' = ANY(d.methods) AND d.cite_key IS NULL
            """,
            (paper_ids,),
        )
        return {row[0] for row in cur.fetchall()}
