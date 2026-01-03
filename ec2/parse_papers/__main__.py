"""
Script that parses papers found in the `paper` table to add to the `theorem` table.
"""

from argparse import ArgumentParser
from .enums import Mode, Method, ArXivPaperSource
from typing import List, Any, Dict
from ..printing.scripts import print_script_header
from ..rds.query import build_query, get_query_count
from ..rds.connect import get_rds_connection
from ..rds.upsert import upsert_rows
from tqdm import tqdm
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import nullcontext
from ..rds.paginate import paginate_query
from .parse_paper import parse_paper
from tempfile import TemporaryDirectory
from pathlib import Path
from .lib.download_paper import download_paper
from .types import Theorem

THEOREM_TYPES = ["theorem", "lemma", "corollary", "proposition"]


def _to_theorem_row(theorem: Theorem, paper_id: str, method: Method) -> Dict[str, Any]:
    return {
        "paper_id": paper_id,
        "name": " ".join(p for p in [
            theorem["type"].capitalize(),
            theorem["ref"],
            f"({theorem['note']})" if theorem["note"] else None
        ] if p is not None),
        "label": theorem["label"] or None,
        "body": theorem["body"],
        "parsing_method": method.value
    }

def _update_pbar(pbar, parse_successes, parse_attempts):
    parse_attempts += 1
    pbar.update(1)
    pbar.set_postfix({"parse_rate": f"{(100.0 * parse_successes / parse_attempts):.2f}%"})

    return parse_attempts

def _parse_papers(
    paper_ids: List[str],
    condition: str,
    overwrite: bool,
    batch_size: int,
    workers: int,
    timeout: int,
    arxiv_paper_src: ArXivPaperSource,
    method: Method,
    mode: Mode
):
    if mode != Mode.PRODUCTION:
        workers = 0

        if mode != Mode.DEVELOPMENT:
            timeout = 0

    print_script_header(
        action="Parsing papers from the `paper` table",
        params={
            "paper_ids?": paper_ids,
            "condition?": condition,
            "overwrite": overwrite,
            "batch_size?": batch_size,
            "workers?": workers,
            "timeout?": timeout,
            "arxiv_paper_src": arxiv_paper_src.name,
            "method": method.name,
            "mode": mode.name
        }
    )

    if arxiv_paper_src == ArXivPaperSource.S3:
        base_query = """
            SELECT paper.paper_id, bundle_tar, bytes_start, bytes_end
            FROM paper
            INNER JOIN paper_arxiv_s3_location paper_loc
                ON paper_loc.paper_id = paper.paper_id
        """
    else: # arxiv_paper_src == ArxivPaperSource.API
        base_query = "SELECT paper.paper_id from paper"

    conn = get_rds_connection()

    query, params = build_query(
        base_query,
        where_clauses=[
            {
                "if": len(paper_ids) > 0,
                "condition": "paper.paper_id LIKE ANY(%s)",
                "param": [f"%{pid}%" for pid in paper_ids]
            },
            {
                "if": not overwrite,
                "condition": """
                    NOT EXISTS (
                        SELECT 1 FROM theorem
                        WHERE theorem.paper_id = paper.paper_id
                    )
                """
            },
            {
                "if": condition,
                "condition": condition
            }
        ]
    )

    if mode == Mode.PRODUCTION:
        count = get_query_count(conn, query, params)

        parse_attempts = 0
        parse_successes = 0

        pbar = tqdm(total=count, dynamic_ncols=True)
        ex = ProcessPoolExecutor(max_workers=workers)
    else:
        pbar = nullcontext()
        ex = nullcontext()

    tmpdir = TemporaryDirectory() if mode != Mode.DEBUGGING else nullcontext()

    with pbar, ex, tmpdir:
        cwd: Path = Path(tmpdir.name) if mode != Mode.DEBUGGING else Path("DEBUG")
        cwd.mkdir(exist_ok=True)

        for papers in paginate_query(
            conn,
            base_query=query,
            base_params=params,
            order_by="paper_id",
            page_size=batch_size
        ):
            batch_theorem_rows = []

            if mode == Mode.PRODUCTION:
                fut_to_pid = {}

            for paper in papers:
                paper_id = paper["paper_id"]
                arxiv_s3_loc = (
                    paper["bundle_tar"], paper["bytes_start"], paper["bytes_end"]
                ) if arxiv_paper_src == ArXivPaperSource.S3 else None

                try:
                    paper_dir = download_paper(
                        paper_id,
                        arxiv_s3_loc,
                        cwd,
                        mode
                    )
                except Exception as e:
                    if mode == Mode.DEVELOPMENT:
                        print(f"[DEV] {paper_id} (Download): {e}")
                    elif mode == Mode.DEBUGGING:
                        raise e
                    else:
                        parse_attempts = _update_pbar(pbar, parse_successes, parse_attempts)

                    continue

                if mode == Mode.PRODUCTION:
                    fut = ex.submit(
                        parse_paper,
                        str(paper_dir),
                        THEOREM_TYPES,
                        timeout,
                        mode,
                        method
                    )
                    fut_to_pid[fut] = paper_id
                else:
                    try:
                        theorems = parse_paper(
                            paper_dir,
                            THEOREM_TYPES,
                            timeout,
                            mode,
                            method
                        )
                    except Exception as e:
                        if mode == Mode.DEVELOPMENT:
                            print(f"[DEV] {paper_id} (Parse): {e}")
                            continue
                        elif mode == Mode.DEBUGGING:
                            raise e

                    if theorems:
                        batch_theorem_rows.extend([_to_theorem_row(t, paper_id, method) for t in theorems])

                        if mode == Mode.DEVELOPMENT:
                            print(f"[DEV] {paper_id}: Successfully parsed {len(theorems)} theorems")
                    elif mode == Mode.DEVELOPMENT:
                        print(f"[DEV] {paper_id}: No theorems found")

            if mode == Mode.PRODUCTION:
                for fut in as_completed(fut_to_pid):
                    paper_id = fut_to_pid[fut]

                    try:
                        theorems = fut.result()
                    except Exception:
                        theorems = None

                    if theorems:
                        parse_successes += 1
                        batch_theorem_rows.extend([_to_theorem_row(t, paper_id, method) for t in theorems])
                
                    parse_attempts = _update_pbar(pbar, parse_successes, parse_attempts)

            if batch_theorem_rows:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM theorem WHERE paper_id = ANY(%s)",
                        (list({row["paper_id"] for row in batch_theorem_rows}),),
                    )

                    with conn.cursor() as cur:
                        upsert_rows(
                            cur,
                            table="theorem",
                            rows=batch_theorem_rows,
                            on_conflict={
                                "with": ["paper_id", "name"],
                                "replace": ["body", "label", "parsing_method"]
                            }
                        )

                if mode != Mode.DEBUGGING:
                    conn.commit()

if __name__ == "__main__":
    arg_parser = ArgumentParser()

    arg_parser.add_argument(
        "--paper-ids",
        type=str,
        nargs="+",
        default=[],
        help="List of paper IDs to parse. By default, every paper"
    )

    arg_parser.add_argument(
        "--condition",
        type=str,
        default="",
        help="SQL condition to filter papers"
    )

    arg_parser.add_argument(
        "-o", "--overwrite",
        action="store_true",
        help="Whether to overwrite theorems from previously parsed papers. By default, False"
    )

    arg_parser.add_argument(
        "--batch-size",
        type=int,
        default=128,
        help="Number of papers to attempt to parse concurrently. Only useful in PRODUCTION mode"
    )

    arg_parser.add_argument(
        "--workers",
        type=int,
        default=32,
        help="Number of workers used to parse each batch of papers. Only useful in PRODUCTION mode"
    )

    arg_parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Number of seconds allowed to parse a single paper. Only useful in PRODUCTION or DEVELOPMENT modes"
    )

    arg_parser.add_argument(
        "--arxiv-paper-src",
        type=ArXivPaperSource,
        default=ArXivPaperSource.S3,
        help="Source to download arXiv papers from. By default, S3"
    )

    arg_parser.add_argument(
        "--method",
        type=Method,
        default=Method.PLASTEX,
        help="Method to parse papers with. By default, PLASTEX"
    )

    arg_parser.add_argument(
        "--mode",
        type=Mode,
        default=Mode.DEVELOPMENT,
        help="Mode to parse papers in. By default, DEVELOPMENT"
    )

    args = arg_parser.parse_args()

    _parse_papers(
        paper_ids=args.paper_ids,
        condition=args.condition,
        overwrite=args.overwrite,
        batch_size=args.batch_size,
        workers=args.workers,
        timeout=args.timeout,
        arxiv_paper_src=args.arxiv_paper_src,
        method=args.method,
        mode=args.mode
    )