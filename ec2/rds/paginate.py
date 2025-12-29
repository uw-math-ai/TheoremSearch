from typing import Any, Dict, Iterator, List, Tuple
from psycopg2.extensions import connection
from psycopg2 import sql

def paginate_query(
    conn: connection,
    base_query: str,
    order_by: str,
    base_params: List[Any] = [],
    descending: bool = False,
    page_size: int = 100,
    skip: int = 0
) -> Iterator[List[Dict[str, Any]]]:
    """
    Paginates a SQL query. Helpful for reading large query results into manageable pages.

    Works by ordering results of a query by a stable key. Ensure the table or join you are
    querying includes a column that provides such a stable key.

    Parameters
    ----------
    conn : connection
        Connection to a RDS database
    base_query : str
        A valid SQL query. Use `%s` for dynamic parameters. Do not include ORDER BY or OFFSET
        clauses
    order_by : str
        The stable ordering key
    base_params : List[Any], optional
        The dynamic parameters of `base_query`. Must match up with each `%s` in `base_query`. By
        default, []
    descending : bool, optional
        Whether to sort `order_by` in descending order. Otherwise, sorts `order_by` in ascending
        order. By default, False
    page_size : int, optional
        The number of rows returned per page. The last page may have fewer rows. By default, 100
    skip: int, optional
        The number of rows to skip. By default, 0

    Returns
    -------
    paginator : Iterator[List[Dict[str, Any]]]
        An iterator of pages of rows. Each page is a List and each row is a Dict mapping a column
        name to the column value
    """

    after_value = None
    order_ident = sql.Identifier(order_by)
    direction = sql.SQL(" DESC") if descending else sql.SQL(" ASC")
    cmp_op = sql.SQL("<") if descending else sql.SQL(">")

    first_page = True

    while True:
        parts = [
            sql.SQL("SELECT * FROM ("),
            sql.SQL(base_query),
            sql.SQL(") AS t")
        ]

        params = base_params.copy()

        if after_value is not None:
            parts += [
                sql.SQL(" WHERE "),
                order_ident,
                sql.SQL(" "),
                cmp_op,
                sql.SQL(" "),
                sql.Placeholder()
            ]
            params.append(after_value)

        parts += [
            sql.SQL(" ORDER BY "),
            order_ident,
            direction
        ]

        if first_page and skip > 0:
            parts += [sql.SQL(" OFFSET %s")]
            params.append(skip)

        parts += [sql.SQL(" LIMIT %s")]
        params.append(page_size)

        query = sql.Composed(parts)

        with conn.cursor() as cur:
            cur.execute(query, tuple(params))
            cols = [d[0] for d in cur.description]
            rows_raw = cur.fetchall()

        if not rows_raw:
            break

        rows = [dict(zip(cols, r)) for r in rows_raw]
        yield rows

        after_value = rows[-1][order_by]
        first_page = False