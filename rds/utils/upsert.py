from typing import Any, Dict, List, Optional, Tuple
from psycopg2.extensions import connection
from psycopg2.extras import execute_values


def _dedup_rows(rows: List[Dict[str, Any]], key_cols: List[str]) -> List[Dict[str, Any]]:
    seen: Dict[tuple, int] = {}
    deduped: List[Dict[str, Any]] = []
    for row in rows:
        key = tuple(row.get(c) for c in key_cols)
        if key not in seen:
            seen[key] = len(deduped)
            deduped.append({**row, **({"methods": list(row["methods"])} if "methods" in row else {})})
        elif "methods" in row:
            existing = deduped[seen[key]]
            for m in row["methods"]:
                if m not in existing["methods"]:
                    existing["methods"].append(m)
    return deduped


def _strip_nul(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\x00", "")
    return value


def _clean_row(row: Dict[str, Any]) -> tuple:
    return tuple(_strip_nul(v) for v in row.values())

def _validate_on_conflict(on_conflict: Dict[str, List[str]]):
    if "with" not in on_conflict:
        raise ValueError("'with' is required in on_conflict")
    unknown = set(on_conflict) - {"with", "where", "replace", "update_expr"}
    if unknown:
        raise ValueError(f"unknown keys in on_conflict: {sorted(unknown)}")


def _build_conflict_clause(on_conflict: Dict[str, List[str]]) -> str:
    cols = ", ".join(on_conflict["with"])
    where = on_conflict.get("where", "")
    where_part = f" WHERE {where}" if where else ""
    if on_conflict.get("update_expr"):
        return f"ON CONFLICT ({cols}){where_part} DO UPDATE SET {on_conflict['update_expr']}"
    if on_conflict.get("replace"):
        set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in on_conflict["replace"])
        return f"ON CONFLICT ({cols}){where_part} DO UPDATE SET {set_clause}"
    return f"ON CONFLICT ({cols}){where_part} DO NOTHING"

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

    conflict_clause = ""
    if on_conflict is not None:
        _validate_on_conflict(on_conflict)
        conflict_clause = _build_conflict_clause(on_conflict)

    with conn.cursor() as cur:
        cur.execute(f"""
            INSERT INTO {table} ({", ".join(row.keys())})
            VALUES ({", ".join(["%s"] * len(row))})
            {conflict_clause}
        """, _clean_row(row))

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

    conflict_clause = ""
    if on_conflict is not None:
        _validate_on_conflict(on_conflict)
        conflict_clause = _build_conflict_clause(on_conflict)
        if on_conflict.get("update_expr") and on_conflict.get("with"):
            rows = _dedup_rows(rows, on_conflict["with"])

    with conn.cursor() as cur:
        execute_values(cur, f"""
            INSERT INTO {table} ({", ".join(rows[0].keys())})
            VALUES %s
            {conflict_clause}
        """, [_clean_row(row) for row in rows])

def update_row(
    conn: connection,
    table: str,
    row: Dict[str, Any],
    where: List[str]
):
    """
    Updates a row in a table.

    Parameters
    ----------
    conn : connection
        A SQL connection
    table : str
        The table you want to update
    row : Dict[str, Any]
        The columns to update, a Dict mapping column names to values.
        Must include all keys listed in `where`
    where : List[str]
        The column names in `row` to match on
    """
    update_cols = [col for col in row if col not in where]
    set_clause = ", ".join(f"{col} = %s" for col in update_cols)
    where_clause = " AND ".join(f"{col} = %s" for col in where)

    with conn.cursor() as cur:
        cur.execute(f"""
            UPDATE {table}
            SET {set_clause}
            WHERE {where_clause}
        """, (*[_strip_nul(row[col]) for col in update_cols], *[_strip_nul(row[col]) for col in where]))


def update_rows(
    conn: connection,
    table: str,
    rows: List[Dict[str, Any]],
    where: List[str],
    casts: Optional[Dict[str, str]] = None,
):
    """
    Updates a batch of rows in a table efficiently.

    Parameters
    ----------
    conn : connection
        A SQL connection
    table : str
        The table you want to update
    rows : List[Dict[str, Any]]
        The batch of rows to update. Each row is a Dict mapping column names to values.
        Each row must include all keys listed in `where`
    where : List[str]
        The column names in each row to match on
    casts : Dict[str, str], optional
        Explicit PostgreSQL type casts for columns whose types cannot be inferred from
        the VALUES literal (e.g. {"bibliography": "jsonb"}). By default None.
    """
    casts = casts or {}
    update_cols = [col for col in rows[0] if col not in where]

    def _ref(col):
        return f"v.{col}::{casts[col]}" if col in casts else f"v.{col}"

    with conn.cursor() as cur:
        execute_values(cur, f"""
            UPDATE {table} AS t
            SET {", ".join(f"{col} = {_ref(col)}" for col in update_cols)}
            FROM (VALUES %s) AS v({", ".join(update_cols + where)})
            WHERE {" AND ".join(f"t.{col} = v.{col}" for col in where)}
        """, [(*[_strip_nul(row[col]) for col in update_cols], *[_strip_nul(row[col]) for col in where]) for row in rows])


def insert_rows_returning(
    conn: connection,
    table: str,
    rows: List[Dict[str, Any]],
    returning: str,
) -> List[Any]:
    """
    Inserts a batch of rows and returns a column value for each inserted row.

    Parameters
    ----------
    conn : connection
        A SQL connection
    table : str
        The table to insert into
    rows : List[Dict[str, Any]]
        Rows to insert
    returning : str
        Column name to return for each inserted row

    Returns
    -------
    List[Any]
        Values of the returning column, in insertion order
    """
    with conn.cursor() as cur:
        result = execute_values(cur, f"""
            INSERT INTO {table} ({", ".join(rows[0].keys())})
            VALUES %s
            RETURNING {returning}
        """, [_clean_row(row) for row in rows], fetch=True)
    return [r[0] for r in result]