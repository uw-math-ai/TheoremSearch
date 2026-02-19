from typing import List, Dict, Tuple, Any
from psycopg2.extensions import connection

def _validate_where_clause(where_clause: Dict):
    if "if" not in where_clause:
        raise ValueError("Where clause is missing an 'if'")
    elif "condition" not in where_clause:
        raise ValueError("Where clause is missing a 'condition'")
    elif "param" in where_clause and "params" in where_clause:
        raise ValueError("Where clause cannot have both 'param' and 'params'")

def build_query(
    base_query: str,
    base_params: List[Any] = [],
    where_clauses: List[Dict] = [],
    sample: int = -1
) -> Tuple[str, List[Any]]:
    """
    Builds a SQL query with optional where clauses. Can be used for random sampling.

    Parameters
    ----------
    base_query : str
        A valid SQL query. Use `%s` for dynamic parameters. Only include SELECT and JOIN clauses
    base_params : List[Any], optional
        The dynamic parameters of `base_query`. Must match up with each `%s` in `base_query`. By
        default, []
    where_clauses : List[Dict], optional
        The dynamic where clauses. Each item must be a Dict of the form:
        ```
        {
            "if": bool, # add this conditon to the WHERE clause if this is true
            "condition": str, # the condition to be added
            "param" or "params": List[Any] # the dynamic parameter(s) of the condition
        }
        ```
        By default, []
    sample : int, optional
        The number of rows to randomly sample from the query. If non-positive, does nothing. By
        default, -1

    Returns
    -------
    query: str
        The resulting query. Uses `%s` for dynamic parameters
    params: List[Any]
        The dynamic parameters of `query`
    """

    query = base_query
    params = base_params.copy()

    where_conditions = []
    for where_clause in where_clauses:
        _validate_where_clause(where_clause)

        if where_clause["if"]:
            where_conditions.append(where_clause["condition"])

            if "param" in where_clause:
                params.append(where_clause["param"])
            elif "params" in where_clause:
                params.extend(where_clause["params"])

    if where_conditions:
        query += " WHERE " + " AND ".join(where_conditions)

    if sample > 0:
        query += " ORDER BY RANDOM() LIMIT %s"
        params.append(sample)

    return query, params

def get_query_count(
    conn: connection,
    query: str,
    params: List[Any] = []
) -> int:
    """
    Returns the number of rows returned by a query.

    Parameters
    ----------
    conn : connection
        Connection to a RDS database
    query : str
        A valid SQL query. Use `%s` for dynamic parameters.
    params : List[Any]
        The dynamic parameters of `query`. Must match up with each `%s` in `query`. By default, []
    
    Returns
    -------
    count : int
        The number of rows returned by a query
    """

    count_query = f"""
        SELECT COUNT(*)
        FROM ({query}) AS q
    """

    with conn.cursor() as cur:
        cur.execute(count_query, (*params,))
        count = cur.fetchone()[0]

        return count