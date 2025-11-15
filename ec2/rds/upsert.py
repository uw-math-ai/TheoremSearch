from typing import Dict, List, Optional
from psycopg2.extensions import cursor

def upsert_row(
    cur: cursor, 
    table: str, 
    row: Dict[str, any],
    on_conflict: Optional[Dict[str, List[str]]] = None
):
    if on_conflict is not None:
        if not ("with" in on_conflict and "replace" in on_conflict):
            raise ValueError("both 'with' and 'replace' must be included in on_conflict")
        if len(on_conflict) > 2:
            raise ValueError("on_conflict must be a dictionary of exactly 'with' and 'replace'")

        conflict_clause = "ON CONFLICT "
        conflict_clause += f"({', '.join(on_conflict['with'])}) "
        conflict_clause += "DO UPDATE SET "
        conflict_clause += f"{', '.join(col + ' = EXCLUDED.' + col for col in on_conflict.get('replace', []))}"
    else:
        conflict_clause = ""

    cur.execute(f"""
        INSERT INTO {table} ({", ".join(row.keys())})
        VALUES ({", ".join(["%s"] * len(row))})
        {conflict_clause}
    """, tuple(row.values()))

def upsert_rows(
    cur: cursor, 
    table: str, 
    rows: List[Dict[str, any]],
    on_conflict: Optional[Dict[str, List[str]]] = None
):
    if on_conflict is not None:
        if not ("with" in on_conflict and "replace" in on_conflict):
            raise ValueError("both 'with' and 'replace' must be included in on_conflict")
        if len(on_conflict) > 2:
            raise ValueError("on_conflict must be a dictionary of exactly 'with' and 'replace'")

        conflict_clause = "ON CONFLICT "
        conflict_clause += f"({', '.join(on_conflict['with'])}) "
        conflict_clause += "DO UPDATE SET "
        conflict_clause += f"{', '.join(col + ' = EXCLUDED.' + col for col in on_conflict.get('replace', []))}"
    else:
        conflict_clause = ""

    cur.executemany(f"""
        INSERT INTO {table} ({", ".join(rows[0].keys())})
        VALUES ({", ".join(["%s"] * len(rows[0]))})
        {conflict_clause}
    """, [tuple(row.values()) for row in rows])