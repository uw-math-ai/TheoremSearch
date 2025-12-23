from argparse import ArgumentParser
from ..rds.connect import get_rds_connection
from ..rds.query import build_query
from ..rds.paginate import paginate_query
from ..rds.upsert import upsert_rows
from concurrent.futures import ProcessPoolExecutor, TimeoutError
from tempfile import TemporaryDirectory
from .download_and_extract_paper import download_and_extract_paper
from typing import Tuple, List, Optional, Set
from .regex_method.parse import parse_by_regex
from .tex_method.parse import parse_by_tex
from tqdm import tqdm
from .plastex_method.parse import parse_by_plastex

def _parse_arxiv_paper(
    paper_id: str,
    paper_arxiv_s3_loc: Optional[Tuple[str, int, int]],
    parsing_method: str,
    theorem_types: List[str],
    timeout: int,
    debugging_mode: bool,
    paper_dir: Optional[str] = None
):
    if debugging_mode:
        paper_dir = "parsing_debugging_downloads"

    if not paper_dir:
        with TemporaryDirectory() as temp_paper_dir:
            return _parse_arxiv_paper(
                paper_id, 
                paper_arxiv_s3_loc, 
                parsing_method,
                theorem_types,
                timeout,
                debugging_mode,
                paper_dir=temp_paper_dir
            )
        
    src_dir = download_and_extract_paper(paper_id, paper_arxiv_s3_loc, cwd=paper_dir)

    if parsing_method == "tex":
        theorems = parse_by_tex(paper_id, src_dir, theorem_types, timeout, debugging_mode)
    elif parsing_method == "regex":
        theorems = parse_by_regex(paper_id, src_dir, theorem_types, timeout)
    else:
        theorems = parse_by_plastex(paper_id, src_dir, theorem_types, debugging_mode)
    return theorems

def parse_arxiv_papers(
    # SEARCH
    paper_ids: List[str],
    overwrite: bool,
    skip: int,
    condition: str,
    # CONFIG
    batch_size: int,
    timeout: int,
    workers: int,
    parsing_method: str,
    verbose: bool,
    debugging_mode: bool,
    theorem_types: Set[str] = { "theorem", "lemma", "proposition", "corollary" }
):
    if skip < 0:
        raise ValueError(f"skip must be >= 0, not {skip}")
    elif parsing_method not in { "tex", "regex", "plastex" }:
        raise ValueError(f"parsing_method must be 'tex' or 'regex', not '{parsing_method}'")

    conn = get_rds_connection()

    query, params = build_query(
        base_query="""
            SELECT paper.paper_id, last_updated, bundle_tar, bytes_start, bytes_end
            FROM paper
              INNER JOIN paper_arxiv_s3_location paper_loc
                ON paper_loc.paper_id = paper.paper_id
        """,
        where_clauses=[
            {
                "if": len(paper_ids) > 0,
                "condition": "paper.paper_id LIKE ANY(%s)",
                "param": ["%" + paper_id + "%" for paper_id in paper_ids]
            },
            {
                "if": not overwrite,
                "condition": """
                    NOT EXISTS (
                        SELECT 1
                        FROM theorem
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

    count_query = f"""
        SELECT COUNT(*)
        FROM ({query}) AS q
    """

    with conn.cursor() as count_cur:
        count_cur.execute(count_query, (*params,))
        count = count_cur.fetchone()[0]

        count = max(0, count - skip)

    parse_attempts = 0
    parse_successes = 0

    script_announcement = f"=== Parsing {count} matching arXiv papers ==="
    print(script_announcement)
    print(f"  > overwrite: {overwrite}")
    if skip:
        print(f"  > skip: {skip}")
    if condition:
        print(f"  > condition: {condition}")
    print(f"  > timeout: {timeout}s")
    print(f"  > batch size: {batch_size}")
    print(f"  > workers: {workers}")
    print(f"  > parsing method: {parsing_method}")
    print("=" * len(script_announcement))

    with ProcessPoolExecutor(max_workers=workers) as ex, \
        tqdm(total=count, mininterval=0.1, smoothing=0.1, dynamic_ncols=True) as pbar:
        for papers in paginate_query(
            conn,
            base_sql=query,
            base_params=(*params,),
            order_by="last_updated",
            descending=True,
            page_size=batch_size,
            skip=skip
        ):
            futs_and_paper_ids = []
            batch_theorem_rows = []
            
            for paper in papers:
                parse_attempts += 1

                paper_id = paper["paper_id"]

                if not paper_ids:
                    paper_arxiv_s3_loc = (paper["bundle_tar"], paper["bytes_start"], paper["bytes_end"])
                else:
                    paper_arxiv_s3_loc = None

                fut = ex.submit(
                    _parse_arxiv_paper, 
                    paper_id, 
                    paper_arxiv_s3_loc, 
                    parsing_method, 
                    theorem_types,
                    timeout,
                    debugging_mode
                )
                
                futs_and_paper_ids.append((fut, paper_id))

            for fut, paper_id in futs_and_paper_ids:
                theorem_rows = []

                try:
                    theorem_rows = fut.result(timeout=timeout)

                    if len(theorem_rows) == 0 and verbose:
                        print(f"[NO THEOREMS FOUND] {paper_id}")
                except TimeoutError:
                    if verbose:
                        print(f"[TIMEOUT] {paper_id} (> {timeout}s)")
                except Exception as e:
                    if debugging_mode:
                        raise e

                    if verbose:
                        print(f"[FUTURE ERROR] {paper_id}: {repr(e)[:128]}{'…' if len(repr(e)) > 128 else ''}")

                if theorem_rows:
                    batch_theorem_rows.extend([
                        theorem_row | { "parsing_method": parsing_method }
                        for theorem_row in theorem_rows
                    ])
                    parse_successes += 1

                pbar.update(1)
                pbar.set_postfix({
                    "parse_rate": f"{(100.0 * parse_successes / parse_attempts):.2f}%"
                })

            if batch_theorem_rows:
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

                if not debugging_mode:
                    conn.commit()
                
    conn.close()

if __name__ == "__main__":
    arg_parser = ArgumentParser()

    arg_parser.add_argument(
        "--paper-ids",
        type=str,
        nargs="+",
        default=[],
        help="IDs of papers to parse"
    )

    arg_parser.add_argument(
        "-o", "--overwrite",
        action="store_true",
        help="Whether to overwrite parsed papers"
    )

    arg_parser.add_argument(
        "--skip",
        type=int,
        default=0,
        help="Number of papers to skip parsing"
    )

    arg_parser.add_argument(
        "--condition",
        type=str,
        default="",
        help="An additonal query condition"
    )

    arg_parser.add_argument(
        "--batch-size",
        type=int,
        required=False,
        default=32,
        help="Number of papers per batch"
    )

    arg_parser.add_argument(
        "--timeout",
        type=int,
        required=False,
        default=10,
        help="Number of seconds to wait for a paper to parse"
    )

    arg_parser.add_argument(
        "--workers",
        type=int,
        required=False,
        default=16,
        help="Maximum number of workers"
    )

    arg_parser.add_argument(
        "--parsing-method",
        type=str,
        required=False,
        default="plastex",
        help="Method to parse papers: 'tex' or 'regex'"
    )

    arg_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Whether to print out errors"
    )

    arg_parser.add_argument(
        "-d", "--debugging-mode",
        action="store_true",
        help="Whether to raise errors and save downloaded files in a local folder"
    )

    args = arg_parser.parse_args()

    parse_arxiv_papers(
        # SEARCH
        paper_ids=args.paper_ids,
        overwrite=args.overwrite,
        skip=args.skip,
        condition=args.condition,
        # CONFIG
        batch_size=args.batch_size,
        timeout=args.timeout,
        workers=args.workers,
        parsing_method=args.parsing_method,
        verbose=args.verbose,
        debugging_mode=args.debugging_mode
    )
