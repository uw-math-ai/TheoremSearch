from argparse import ArgumentParser
from concurrent.futures import ProcessPoolExecutor, as_completed, TimeoutError as FutureTimeoutError
from tempfile import TemporaryDirectory
from typing import Tuple, List, Optional, Set, Any
import multiprocessing as mp
import queue as queue_mod
import traceback
import os

from ..rds.connect import get_rds_connection
from ..rds.query import build_query
from ..rds.paginate import paginate_query
from ..rds.upsert import upsert_rows

from .download_and_extract_paper import download_and_extract_paper
from .regex_method.parse import parse_by_regex
from .tex_method.parse import parse_by_tex
from .plastex_method.parse import parse_by_plastex


def _mp_ctx():
    try:
        return mp.get_context("fork")
    except ValueError:
        return mp.get_context("spawn")


def _parse_worker_entry(
    q: Any,
    paper_id: str,
    paper_arxiv_s3_loc: Optional[Tuple[str, int, int]],
    parsing_method: str,
    theorem_types: List[str],
    timeout: int,
    debugging_mode: bool,
    paper_dir: Optional[str],
):
    try:
        if debugging_mode:
            paper_dir = "parsing_debugging_downloads"

        if not paper_dir:
            with TemporaryDirectory() as temp_paper_dir:
                src_dir = download_and_extract_paper(paper_id, paper_arxiv_s3_loc, cwd=temp_paper_dir)
                if parsing_method == "tex":
                    rows = parse_by_tex(paper_id, src_dir, theorem_types, timeout, debugging_mode)
                elif parsing_method == "regex":
                    rows = parse_by_regex(paper_id, src_dir, theorem_types, timeout)
                else:
                    rows = parse_by_plastex(paper_id, src_dir, theorem_types, timeout, debugging_mode)
                q.put(("ok", rows))
                return

        src_dir = download_and_extract_paper(paper_id, paper_arxiv_s3_loc, cwd=paper_dir)
        if parsing_method == "tex":
            rows = parse_by_tex(paper_id, src_dir, theorem_types, timeout, debugging_mode)
        elif parsing_method == "regex":
            rows = parse_by_regex(paper_id, src_dir, theorem_types, timeout)
        else:
            rows = parse_by_plastex(paper_id, src_dir, theorem_types, timeout, debugging_mode)

        q.put(("ok", rows))
    except Exception as e:
        q.put(("err", repr(e), traceback.format_exc()))


def _parse_with_hard_timeout(
    paper_id: str,
    paper_arxiv_s3_loc: Optional[Tuple[str, int, int]],
    parsing_method: str,
    theorem_types: List[str],
    timeout: int,
    debugging_mode: bool,
    paper_dir: Optional[str] = None,
):
    ctx = _mp_ctx()
    q = ctx.Queue(maxsize=1)
    p = ctx.Process(
        target=_parse_worker_entry,
        args=(q, paper_id, paper_arxiv_s3_loc, parsing_method, theorem_types, timeout, debugging_mode, paper_dir),
        daemon=True,
    )
    p.start()
    p.join(timeout)

    if p.is_alive():
        p.terminate()
        p.join(2)
        if p.is_alive():
            try:
                p.kill()
            except Exception:
                pass
        raise TimeoutError(f"{paper_id} exceeded {timeout}s")

    try:
        msg = q.get_nowait()
    except queue_mod.Empty:
        return []

    if msg[0] == "ok":
        return msg[1]
    raise RuntimeError(msg[1] + "\n" + msg[2])


def _parse_one_paper_job(
    paper_id: str,
    paper_arxiv_s3_loc: Optional[Tuple[str, int, int]],
    parsing_method: str,
    theorem_types: List[str],
    timeout: int,
    debugging_mode: bool,
):
    return _parse_with_hard_timeout(
        paper_id=paper_id,
        paper_arxiv_s3_loc=paper_arxiv_s3_loc,
        parsing_method=parsing_method,
        theorem_types=theorem_types,
        timeout=timeout,
        debugging_mode=debugging_mode,
    )


def parse_arxiv_papers(
    paper_ids: List[str],
    overwrite: bool,
    skip: int,
    condition: str,
    batch_size: int,
    timeout: int,
    workers: int,
    parsing_method: str,
    verbose: bool,
    debugging_mode: bool,
    theorem_types: Optional[Set[str]] = None,
):
    if theorem_types is None:
        theorem_types = {"theorem", "lemma", "proposition", "corollary"}

    if skip < 0:
        raise ValueError(f"skip must be >= 0, not {skip}")
    if parsing_method not in {"tex", "regex", "plastex"}:
        raise ValueError(f"parsing_method must be 'tex', 'regex', or 'plastex', not '{parsing_method}'")

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
                "param": ["%" + paper_id + "%" for paper_id in paper_ids],
            },
            {
                "if": not overwrite,
                "condition": """
                    NOT EXISTS (
                        SELECT 1
                        FROM theorem
                        WHERE theorem.paper_id = paper.paper_id
                    )
                """,
            },
            {"if": condition, "condition": condition},
        ],
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

    from tqdm import tqdm

    mp_ctx = _mp_ctx()

    with ProcessPoolExecutor(max_workers=workers, mp_context=mp_ctx) as ex, tqdm(
        total=count, mininterval=0.1, smoothing=0.1, dynamic_ncols=True
    ) as pbar:
        for papers in paginate_query(
            conn,
            base_sql=query,
            base_params=(*params,),
            order_by="last_updated",
            descending=True,
            page_size=batch_size,
            skip=skip,
        ):
            batch_theorem_rows = []
            fut_to_paper_id = {}

            for paper in papers:
                parse_attempts += 1
                paper_id = paper["paper_id"]

                if not paper_ids:
                    paper_arxiv_s3_loc = (paper["bundle_tar"], paper["bytes_start"], paper["bytes_end"])
                else:
                    paper_arxiv_s3_loc = None

                fut = ex.submit(
                    _parse_one_paper_job,
                    paper_id,
                    paper_arxiv_s3_loc,
                    parsing_method,
                    list(theorem_types),
                    timeout,
                    debugging_mode,
                )
                fut_to_paper_id[fut] = paper_id

            for fut in as_completed(fut_to_paper_id):
                paper_id = fut_to_paper_id[fut]
                theorem_rows = []

                try:
                    theorem_rows = fut.result(timeout=timeout + 5)
                    if len(theorem_rows) == 0 and verbose:
                        print(f"[NO THEOREMS FOUND] {paper_id}")
                except (TimeoutError, FutureTimeoutError):
                    if verbose:
                        print(f"[TIMEOUT] {paper_id} (> {timeout}s)")
                except Exception as e:
                    if debugging_mode:
                        raise
                    if verbose:
                        r = repr(e)
                        print(f"[FUTURE ERROR] {paper_id}: {r[:128]}{'…' if len(r) > 128 else ''}")

                if theorem_rows:
                    batch_theorem_rows.extend(
                        [theorem_row | {"parsing_method": parsing_method} for theorem_row in theorem_rows]
                    )
                    parse_successes += 1

                pbar.update(1)
                pbar.set_postfix({"parse_rate": f"{(100.0 * parse_successes / parse_attempts):.2f}%"})

            if batch_theorem_rows:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM theorem
                        WHERE paper_id = ANY(%s)
                    """,
                        (list({row["paper_id"] for row in batch_theorem_rows}),),
                    )

                    upsert_rows(
                        cur,
                        table="theorem",
                        rows=batch_theorem_rows,
                        on_conflict={
                            "with": ["paper_id", "name"],
                            "replace": ["body", "label", "parsing_method"],
                        },
                    )

                if not debugging_mode:
                    conn.commit()

    conn.close()


if __name__ == "__main__":
    arg_parser = ArgumentParser()

    arg_parser.add_argument("--paper-ids", type=str, nargs="+", default=[], help="IDs of papers to parse")
    arg_parser.add_argument("-o", "--overwrite", action="store_true", help="Whether to overwrite parsed papers")
    arg_parser.add_argument("--skip", type=int, default=0, help="Number of papers to skip parsing")
    arg_parser.add_argument("--condition", type=str, default="", help="An additonal query condition")
    arg_parser.add_argument("--batch-size", type=int, required=False, default=32, help="Number of papers per batch")
    arg_parser.add_argument("--timeout", type=int, required=False, default=10, help="Seconds to wait per paper")
    arg_parser.add_argument("--workers", type=int, required=False, default=16, help="Maximum number of workers")
    arg_parser.add_argument(
        "--parsing-method", type=str, required=False, default="plastex", help="Method: 'tex', 'regex', or 'plastex'"
    )
    arg_parser.add_argument("-v", "--verbose", action="store_true", help="Whether to print out errors")
    arg_parser.add_argument(
        "-d", "--debugging-mode", action="store_true", help="Whether to raise errors and save downloads locally"
    )

    args = arg_parser.parse_args()

    parse_arxiv_papers(
        paper_ids=args.paper_ids,
        overwrite=args.overwrite,
        skip=args.skip,
        condition=args.condition,
        batch_size=args.batch_size,
        timeout=args.timeout,
        workers=args.workers,
        parsing_method=args.parsing_method,
        verbose=args.verbose,
        debugging_mode=args.debugging_mode,
    )