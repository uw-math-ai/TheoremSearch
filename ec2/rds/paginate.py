from typing import Any, Dict, Iterator, List, Tuple
from psycopg2.extensions import connection
from psycopg2 import sql

def paginate_query(
    conn: connection,
    base_sql: str,
    base_params: Tuple[Any, ...],
    order_by: str,
    page_size: int = 100,
    descending: bool = False,
) -> Iterator[List[Dict[str, Any]]]:
    after_value = None
    order_ident = sql.Identifier(order_by)
    direction = sql.SQL(" DESC") if descending else sql.SQL(" ASC")
    cmp_op = sql.SQL("<") if descending else sql.SQL(">")

    while True:
        parts = [
            sql.SQL("SELECT * FROM ("),
            sql.SQL(base_sql),
            sql.SQL(") AS t")
        ]

        params: List[Any] = list(base_params)

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
            direction,
            sql.SQL(" LIMIT %s")
        ]
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
