import json
from tqdm import tqdm
from typing import List
from datetime import datetime, timezone
from concurrent.futures import ProcessPoolExecutor, as_completed
from argparse import ArgumentParser
from arXiTeX.types import TheoremValidationLevel
from arXiTeX import parse_paper
from rds.utils.connect import get_rds_connection
from rds.utils.query import build_query, get_query_count
from rds.utils.paginate import paginate_query
from rds.utils.upsert import upsert_rows
from ..printing import print_script_header

def parse_papers(
    condition: str,
    condition_params: List[str],
    overwrite: bool,
    batch_size: int,
    workers: int,
    timeout: int,
    validation_level: TheoremValidationLevel,
    source_from_s3: bool
):
    print_script_header(
        action="Parsing papers into theorems",
        params={
            "condition?": condition,
            "condition params?": condition_params,
            "overwrite": overwrite,
            "batch size": batch_size,
            "workers": workers,
            "timeout": timeout,
            "validation level": validation_level.value,
            "source": "arXiv S3 bucket" if source_from_s3 else "arXiv API"
        }
    )

    conn = get_rds_connection("v2")

    query, params = build_query(
        base_query="""
            SELECT paper.id, s3_location.bundle_key, s3_location.bytes_range
            FROM paper
            INNER JOIN s3_location
            ON s3_location.arxiv_id = paper.id AND s3_location.source = paper.source
        """ if source_from_s3 else "SELECT paper.id FROM paper",
        where_clauses=[
            {
                "if": not overwrite,
                "condition": """
                    NOT EXISTS (
                        SELECT 1 from theorem
                        WHERE theorem.paper_id = paper.id and theorem.source = paper.source
                    )
                """
            },
            {
                "if": condition,
                "condition": condition,
                "params": condition_params
            },
            {
                "if": True,
                "condition": "paper.source = 'arXiv'"
            }
        ]
    )

    paper_count = get_query_count(conn, query, params)
   
    status_counts = {
        "success": 0,
        "failed": 0
    }

    pbar = tqdm(total=paper_count, dynamic_ncols=True)
    ex = ProcessPoolExecutor(max_workers=workers)

    with pbar, ex:
        for papers in paginate_query(
            conn,
            base_query=query,
            base_params=params,
            order_by="id",
            page_size=batch_size
        ):
            fut_to_paper_id = {}
            batch_theorem_rows = []
            batch_parse_status_rows = []

            current_time = datetime.now(timezone.utc)

            for paper in papers:
                paper_id = paper["id"]

                s3_bundle_key = paper.get("bundle_key", None)
                s3_bytes_range = paper.get("bytes_range", None)


                fut = ex.submit(
                    parse_paper,
                    paper_id,
                    s3_bundle_key,
                    s3_bytes_range,
                    None,
                    validation_level,
                    timeout
                )
                fut_to_paper_id[fut] = paper_id

            for fut in as_completed(fut_to_paper_id):
                paper_id = fut_to_paper_id[fut]
                error = None

                try:
                    theorems = fut.result()

                    if theorems is None:
                        raise RuntimeError() # this shouldn't happen
                    elif not theorems:
                        raise RuntimeError("[EMPTY ERROR] No theorems found")
                except Exception as e:
                    error = str(e) or "[UNHANDLED ERROR]"
                    theorems = None

                if not theorems:
                    status_counts["failed"] += 1
                else:
                    status_counts["success"] += 1

                batch_parse_status_rows.append({
                    "paper_id": paper_id,
                    "source": "arXiv",
                    "last_parse_attempt_at": current_time,
                    "error": error,
                    "s3": source_from_s3,
                    "validation_level": validation_level.value
                })

                if theorems:
                    batch_theorem_rows.extend([
                        json.loads(theorem.model_dump_json()) | {
                            "paper_id": paper_id,
                            "source": "arXiv"
                        }
                        for theorem in theorems
                    ])

                pbar.update()

                parse_attempts = sum(status_counts.values())
            
                pbar.set_postfix({
                    status: f"{(100.0 * count / parse_attempts):.2f}%"
                    for status, count in status_counts.items()
                })

            upsert_rows(
                conn,
                table="parse_status",
                rows=batch_parse_status_rows,
                on_conflict={
                    "with": ["paper_id", "source"],
                    "replace": ["last_parse_attempt_at", "error", "s3"]
                }
            )

            if batch_theorem_rows:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM theorem WHERE paper_id = ANY(%s) and source = 'arXiv'",
                        (list({row["paper_id"] for row in batch_theorem_rows}),),
                    )

                upsert_rows(
                    conn,
                    table="theorem",
                    rows=batch_theorem_rows
                )

            conn.commit()

if __name__ == "__main__":
    arg_parser = ArgumentParser()

    arg_parser.add_argument(
        "-c",
        "--condition",
        type=str,
        nargs="+",
        help="SQL condition to filter papers followed by its arguments. 'paper' table is available"
    )

    arg_parser.add_argument(
        "-o",
        "--overwrite",
        action="store_true",
        help="Whether to overwrite theorems from previously parsed papers. By default, False"
    )

    arg_parser.add_argument(
        "-b",
        "--batch-size",
        type=int,
        default=64,
        help="Number of papers parsed in one batch with workers. By default, 64"
    )

    arg_parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=8,
        help="Number of workers used to parse a batch of papers. By default, 8"
    )

    arg_parser.add_argument(
        "-t",
        "--timeout",
        type=int,
        default=10,
        help="Number of seconds allows to parse a single paper. By default, 10 seconds"
    )

    arg_parser.add_argument(
        "-v",
        "--validation-level",
        type=TheoremValidationLevel,
        required=False,
        default=TheoremValidationLevel.Paper,
        help="Level to validate theorems. Supported: paper (default), theorem"
    )

    arg_parser.add_argument(
        "-s3",
        "--source-from-s3",
        action="store_true",
        help="Whether to source paper sources from S3. By default, API"
    )

    args = arg_parser.parse_args()

    if args.condition and len(args.condition) >= 2:
        condition, *condition_params = args.condition
    else:
        condition = args.condition[0] if args.condition else None
        condition_params = []

    parse_papers(
        condition=condition,
        condition_params=condition_params,
        overwrite=args.overwrite,
        batch_size=args.batch_size,
        workers=args.workers,
        timeout=args.timeout,
        validation_level=args.validation_level,
        source_from_s3=args.source_from_s3
    )