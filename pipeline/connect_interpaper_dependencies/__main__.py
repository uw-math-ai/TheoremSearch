from tqdm import tqdm
from typing import List
from argparse import ArgumentParser
from .get_interpaper_dependencies import get_interpaper_dependencies
from ..printing import print_script_header
from rds.utils.connect import get_rds_connection
from rds.utils.query import build_query, get_query_count
from rds.utils.paginate import paginate_query
from rds.utils.upsert import upsert_rows

def connect_interpaper_dependencies(
    condition: str,
    condition_params: List[str],
    overwrite: bool,
    batch_size: int,
    similarity_threshold: float
):
    print_script_header(
        action="Connecting interpaper theorem dependencies",
        params={
            "condition": condition,
            "condition params": condition_params,
            "overwrite": overwrite,
            "batch size": batch_size,
            "similarity threshold": similarity_threshold
        }
    )

    conn = get_rds_connection("v2")

    # Pull arXiv papers that have reference_ids and at least one statement.
    # reference_ids are stored as e.g. ["ARXIV:2109.06451", "DOI:10.1000/xyz"].
    # We filter to only ARXIV:-prefixed entries downstream in get_interpaper_dependencies.
    query, params = build_query(
        base_query="""
            SELECT p.paper_id, p.external_id, m.reference_ids
            FROM paper p
            INNER JOIN arxiv_paper_metadata m ON m.arxiv_id = p.external_id
        """,
        where_clauses=[
            {
                "if": condition,
                "condition": condition,
                "params": condition_params
            },
            {
                "if": not overwrite,
                "condition": """
                    NOT EXISTS (
                        SELECT 1 FROM dependency d
                        INNER JOIN statement s ON s.statement_id = d.source_id
                        WHERE s.paper_id = p.paper_id
                          AND d.interpaper IS TRUE
                    )
                """
            },
            {
                "if": True,
                "condition": """
                    EXISTS (
                        SELECT 1 FROM statement s
                        WHERE s.paper_id = p.paper_id
                    )
                """
            },
            {
                "if": True,
                "condition": "kind = 'paper'"
            }
        ]
    )

    count = get_query_count(conn, query)

    with tqdm(total=count, dynamic_ncols=True, unit=" papers") as pbar:
        for papers in paginate_query(
            conn,
            base_query=query,
            base_params=params,
            order_by="paper_id",
            page_size=batch_size
        ):
            batch_rows: List = []

            for paper in papers:
                rows = get_interpaper_dependencies(
                    conn=conn,
                    arxiv_id=paper["external_id"],
                    reference_ids=paper["reference_ids"] or [],
                    similarity_threshold=similarity_threshold,
                )
                batch_rows.extend(rows)

            if batch_rows:
                resolved_rows   = [r for r in batch_rows if r["dep_id"] is not None]
                unresolved_rows = [r for r in batch_rows if r["dep_id"] is None]
                source_ids = list({row["source_id"] for row in batch_rows})

                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM dependency
                        WHERE interpaper IS TRUE
                          AND source_id::TEXT = ANY(%s)
                        """,
                        (source_ids,)
                    )

                if resolved_rows:
                    upsert_rows(conn, table="dependency", rows=resolved_rows)

                if unresolved_rows:
                    with conn.cursor() as cur:
                        cur.executemany(
                            """
                            INSERT INTO dependency
                                (source_id, cite_id, dep_id, kind, interpaper,
                                 cite_key, dep_key, dep_name)
                            VALUES
                                (%(source_id)s, %(cite_id)s, NULL, %(kind)s, %(interpaper)s,
                                 %(cite_key)s, %(dep_key)s, %(dep_name)s)
                            ON CONFLICT DO NOTHING
                            """,
                            unresolved_rows
                        )

                conn.commit()

            pbar.update(len(papers))

if __name__ == "__main__":
    arg_parser = ArgumentParser()

    arg_parser.add_argument(
        "-c",
        "--condition",
        type=str,
        nargs="+",
        help="SQL condition to filter"
    )

    arg_parser.add_argument(
        "-o",
        "--overwrite",
        action="store_true",
        help="Whether to overwrite theorem dependencies"
    )

    arg_parser.add_argument(
        "-b",
        "--batch-size",
        type=int,
        default=64,
        help="Number of papers parsed in one batch with workers. By default, 64"
    )

    arg_parser.add_argument(
        "-s",
        "--similarity-threshold",
        type=float,
        default=0.8
    )

    args = arg_parser.parse_args()

    if args.condition and len(args.condition) >= 2:
        condition, *condition_params = args.condition
    else:
        condition = args.condition[0] if args.condition else None
        condition_params = []

    connect_interpaper_dependencies(
        condition=condition,
        condition_params=condition_params,
        overwrite=args.overwrite,
        batch_size=args.batch_size,
        similarity_threshold=args.similarity_threshold
    )