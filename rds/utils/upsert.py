from typing import Dict, List, Optional, Any
from psycopg2.extensions import connection

def _validate_on_conflict(on_conflict: Dict[str, List[str]]):
    if not ("with" in on_conflict and "replace" in on_conflict):
        raise ValueError("both 'with' and 'replace' must be included in on_conflict")
    if len(on_conflict) > 2:
        raise ValueError("on_conflict must be a dictionary of exactly 'with' and 'replace'")

def upsert_row(
    conn: connection, 
    table: str, 
    row: Dict[str, any],
    on_conflict: Optional[Dict[str, List[str]]] = None
):
    """
    Upserts a row into a table.

    Parameters
    ----------
    conn : connection
        A SQL connection
    table : str
        The table you want to add rows into
    row : Dict[str, Any]
        The row to add into the table, a Dict mapping column names to values
    on_conflict : Optional[Dict[str, List[str]]], optional
        A config object for dealing with row conflict with the following form:
        ```
        {
            "with": List[str] # handle a conflict where the following columns all collide
            "replace": List[str] # replace these existing columns with new values
        }
        ```
        By default None
    """

    if on_conflict is not None:
        _validate_on_conflict(on_conflict)

        conflict_clause = "ON CONFLICT "
        conflict_clause += f"({', '.join(on_conflict['with'])}) "
        conflict_clause += "DO UPDATE SET "
        conflict_clause += f"{', '.join(col + ' = EXCLUDED.' + col for col in on_conflict.get('replace', []))}"
    else:
        conflict_clause = ""

    with conn.cursor() as cur:
        cur.execute(f"""
            INSERT INTO {table} ({", ".join(row.keys())})
            VALUES ({", ".join(["%s"] * len(row))})
            {conflict_clause}
        """, tuple(row.values()))

def upsert_rows(
    conn: connection, 
    table: str, 
    rows: List[Dict[str, Any]],
    on_conflict: Optional[Dict[str, List[str]]] = None
):
    """
    Upserts a batch of a rows into a table efficiently.

    Parameters
    ----------
    cur: connection
        A SQL connection
    table: str
        The table you want to add rows into
    rows: List[Dict[str, Any]]
        The batch of rows to add into the table. Each row is a Dict mapping column names to values
    on_conflict: Optional[Dict[str, List[str]]], optional
        A config object for dealing with row conflict with the following form:
        ```
        {
            "with": List[str] # handle a conflict where the following columns all collide
            "replace": List[str] # replace these existing columns with new values
        }
        ```
        By default None
    """

    if on_conflict is not None:
        _validate_on_conflict(on_conflict)

        conflict_clause = "ON CONFLICT "
        conflict_clause += f"({', '.join(on_conflict['with'])}) "
        conflict_clause += "DO UPDATE SET "
        conflict_clause += f"{', '.join(col + ' = EXCLUDED.' + col for col in on_conflict.get('replace', []))}"
    else:
        conflict_clause = ""
    with conn.cursor() as cur:
        cur.executemany(f"""
            INSERT INTO {table} ({", ".join(rows[0].keys())})
            VALUES ({", ".join(["%s"] * len(rows[0]))})
            {conflict_clause}
        """, [tuple(row.values()) for row in rows])