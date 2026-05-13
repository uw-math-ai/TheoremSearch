"""
Parse papers across any registered source and persist statements + per-source
metadata. Source-specific behavior (download routine, where preamble /
bibliography land, whether to track parse status) lives in
``pipeline.parse_papers.sources``. Adding a new source = adding one Source
subclass; this file stays unchanged.
"""

import time
from argparse import ArgumentParser
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from tqdm import tqdm

from arXiTeX.types import ParseFocus, ParsingMethod, StatementValidationLevel
from rds.utils.connect import get_rds_connection
from rds.utils.paginate import paginate_query
from rds.utils.query import build_query, get_query_count
from rds.utils.upsert import insert_rows_returning, upsert_rows
from ..constants import STATEMENT_KINDS
from ..printing import print_script_header
from .sources import SOURCES, ParseAttempt
from .worker import parse_in_worker


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

@contextmanager
def _timer(label: str, enabled: bool):
    if not enabled:
        yield
        return
    t = time.perf_counter()
    yield
    print(f"[timer] {label}: {time.perf_counter() - t:.3f}s")


def _or_join(clauses: List[Optional[str]]) -> str:
    """OR-join non-empty source SQL fragments, falling back to FALSE."""
    real = [c for c in clauses if c]
    if not real:
        return "FALSE"
    return "(" + " OR ".join(f"({c})" for c in real) + ")"


def _overwrite_condition(focus: ParseFocus) -> str:
    """WHERE fragment that filters out papers already processed under the
    given focus. ``paper`` is in scope."""
    statement_done = (
        "EXISTS (SELECT 1 FROM statement WHERE statement.paper_id = paper.paper_id)"
    )
    preamble_done = _or_join([s.preamble_done_sql() for s in SOURCES.values()])
    bibliography_done = _or_join([s.bibliography_done_sql() for s in SOURCES.values()])

    match focus:
        case ParseFocus.STATEMENTS:
            return f"NOT {statement_done}"
        case ParseFocus.PREAMBLE:
            return f"NOT {preamble_done}"
        case ParseFocus.BIBLIOGRAPHY:
            return f"NOT {bibliography_done}"
        case ParseFocus.ALL:
            return f"NOT ({statement_done} AND {preamble_done} AND {bibliography_done})"


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def parse_papers(
    condition: str,
    condition_params: List[str],
    focus: ParseFocus,
    context: int,
    overwrite: bool,
    batch_size: int,
    workers: int,
    timeout: int,
    parsing_method: ParsingMethod,
    validation_level: StatementValidationLevel,
    shard: int = 0,
    n_shards: int = 1,
    timings: bool = False,
):
    if timeout < 0:
        timeout = None

    print_script_header(
        action="Parsing papers",
        params={
            "focus": focus.value,
            "context": context,
            "condition?": condition,
            "condition params?": condition_params,
            "overwrite": overwrite,
            "batch size": batch_size,
            "workers": workers,
            "timeout": timeout,
            "sources": ", ".join(SOURCES.keys()),
            **(
                {
                    "parsing method": parsing_method.value,
                    "validation level": validation_level.value,
                }
                if focus in (ParseFocus.ALL, ParseFocus.STATEMENTS)
                else {}
            ),
            "shard": f"{shard}/{n_shards}" if n_shards > 1 else "off",
        }
    )

    conn = get_rds_connection("v2")

    query, params = build_query(
        base_query=(
            "SELECT paper.paper_id, paper.external_id, paper.kind, paper.source FROM paper"
            + (" LEFT JOIN arxiv_paper_metadata AS apm ON apm.arxiv_id = paper.external_id" if condition and "apm." in condition else "")
            + (" LEFT JOIN arxiv_parse_status AS aps ON aps.arxiv_id = paper.external_id" if condition and "aps." in condition else "")
        ),
        where_clauses=[
            {
                "if": not overwrite,
                "condition": _overwrite_condition(focus),
            },
            {
                "if": condition,
                "condition": condition,
                "params": condition_params,
            },
            {
                "if": True,
                "condition": "paper.source = ANY(%s)",
                "params": [list(SOURCES.keys())],
            },
            {
                "if": True,
                "condition": "paper.kind IN ('paper', 'blueprint')",
            },
            {
                "if": n_shards > 1,
                "condition": "ABS(hashtext(paper.paper_id::text)) %% %s = %s",
                "params": [n_shards, shard],
            },
        ]
    )

    paper_count = get_query_count(conn, query, params)

    do_statements = focus in (ParseFocus.ALL, ParseFocus.STATEMENTS)

    # Kwargs handed to arXiTeX.parse_paper inside each worker — identical
    # across papers, set once.
    parse_kwargs = {
        "statement_kinds": STATEMENT_KINDS,
        "parsing_method": parsing_method,
        "validation_level": validation_level,
        "timeout": timeout,
        "focus": focus,
        "context": context,
    }

    status_counts = {"success": 0, "failed": 0}

    pbar = tqdm(total=paper_count, dynamic_ncols=True)
    ex = ProcessPoolExecutor(max_workers=workers, max_tasks_per_child=50)

    with pbar, ex:
        for papers in paginate_query(
            conn,
            base_query=query,
            base_params=params,
            order_by="external_id",
            page_size=batch_size,
        ):
            # 1. Group this page by source, then let each source prefetch
            #    whatever metadata its workers will need to materialize the
            #    paper (lookups happen here, in the parent, with DB access).
            by_source: Dict[str, list] = defaultdict(list)
            for paper in papers:
                by_source[paper["source"]].append(paper)

            prefetched_by_source: Dict[str, Dict[str, Dict[str, Any]]] = {}
            for src_name, src_papers in by_source.items():
                src = SOURCES[src_name]
                with _timer(f"prefetch {src_name}", timings):
                    prefetched_by_source[src_name] = src.prefetch_metadata(
                        conn, [p["external_id"] for p in src_papers]
                    )

            # 2. Submit to the worker pool.
            fut_to_paper: Dict[Any, Dict[str, Any]] = {}
            for paper in papers:
                src_name = paper["source"]
                ext_id = paper["external_id"]
                prefetched = prefetched_by_source[src_name].get(ext_id, {})
                fut = ex.submit(
                    parse_in_worker,
                    src_name,
                    ext_id,
                    prefetched,
                    parse_kwargs,
                )
                fut_to_paper[fut] = paper

            # 3. Collect results into per-source batches plus the common
            #    statement / informal_metadata batches.
            source_batches: Dict[str, Dict[str, list]] = defaultdict(dict)
            batch_statement_rows: list = []
            batch_informal_metadata_rows: list = []

            for fut in as_completed(fut_to_paper):
                paper = fut_to_paper[fut]
                src_name = paper["source"]
                src = SOURCES[src_name]
                when = datetime.now(timezone.utc)

                error: Optional[str] = None
                result = None
                try:
                    result = fut.result()
                    if do_statements and not result.statements:
                        raise RuntimeError()  # shouldn't happen
                except Exception as e:
                    error = str(e) or "[UNHANDLED ERROR]"
                    result = None

                status_counts["success" if result is not None else "failed"] += 1

                # Hand the source its slice of the result; it decides what to
                # stage and into which table.
                attempt = ParseAttempt(
                    external_id=paper["external_id"],
                    when=when,
                    error=error,
                    parsing_method=parsing_method,
                    validation_level=validation_level,
                    preamble=getattr(result, "preamble", None),
                    bibliography=getattr(result, "bibliography", None),
                    bibliography_bibtex=getattr(result, "bibliography_bibtex", None),
                )
                if do_statements or result is not None:
                    src.record_attempt(attempt, source_batches[src_name])

                # statement + informal_metadata are common across sources.
                if result is not None and result.statements:
                    batch_statement_rows.extend([
                        {
                            "paper_id": paper["paper_id"],
                            "formality": "informal",
                            "kind": statement.kind,
                            "body": statement.body,
                            "proof": statement.proof,
                        }
                        for statement in result.statements
                    ])
                    batch_informal_metadata_rows.extend([
                        {
                            "ordinal": ordinal,
                            "ref": statement.ref,
                            "label": statement.label,
                            "note": statement.note,
                            "pre_context": statement.pre_context,
                            "post_context": statement.post_context,
                        }
                        for ordinal, statement in enumerate(result.statements)
                    ])

                pbar.update()
                attempts = sum(status_counts.values())
                pbar.set_postfix({
                    status: f"{(100.0 * count / attempts):.2f}%"
                    for status, count in status_counts.items()
                })

            # 4. Flush.
            if batch_statement_rows:
                paper_ids = list({row["paper_id"] for row in batch_statement_rows})
                with _timer("delete statement", timings), conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM statement WHERE paper_id = ANY(%s::uuid[])",
                        (paper_ids,),
                    )
                with _timer("insert statement", timings):
                    inserted_ids = insert_rows_returning(
                        conn,
                        table="statement",
                        rows=batch_statement_rows,
                        returning="statement_id",
                    )
                with _timer("insert informal_metadata", timings):
                    upsert_rows(
                        conn,
                        table="informal_metadata",
                        rows=[
                            {"statement_id": sid, **meta}
                            for sid, meta in zip(inserted_ids, batch_informal_metadata_rows)
                        ],
                    )

            for src_name, batch in source_batches.items():
                if not batch:
                    continue
                with _timer(f"commit {src_name} batch", timings):
                    SOURCES[src_name].commit_batch(conn, batch)

            with _timer("commit", timings):
                conn.commit()

            pbar.update(0)  # flush postfix


if __name__ == "__main__":
    arg_parser = ArgumentParser(
        description="Parse papers from any registered source and persist results."
    )

    arg_parser.add_argument(
        "-f", "--focus",
        type=ParseFocus,
        default=ParseFocus.ALL,
        choices=[f.value for f in ParseFocus],
        help="What to parse: all (default), statements, preamble, or bibliography. "
             "Only work for the selected focus is done, and --overwrite only applies within it."
    )

    arg_parser.add_argument(
        "-x", "--context",
        type=int,
        default=0,
        help="Amount of context (number of characters) to grab before and after a parsed statement"
    )

    arg_parser.add_argument(
        "-c", "--condition",
        type=str,
        nargs="+",
        metavar=("SQL", "PARAM"),
        help="SQL WHERE condition to filter papers, followed by any bind parameters. "
             "The 'paper' table is in scope. "
             "Example: -c \"paper.external_id = %%s\" 2301.00001"
    )

    arg_parser.add_argument(
        "-o", "--overwrite",
        action="store_true",
        help="Re-parse and overwrite papers that already have data for the active focus. "
             "Default: skip them."
    )

    arg_parser.add_argument(
        "-b", "--batch-size",
        type=int,
        default=64,
        help="Papers dispatched to the worker pool per iteration. Default: 64."
    )

    arg_parser.add_argument(
        "-w", "--workers",
        type=int,
        default=8,
        help="Parallel worker processes. Default: 8."
    )

    arg_parser.add_argument(
        "-t", "--timeout",
        type=int,
        default=10,
        help="Per-paper parse timeout in seconds. -1 = no limit. Default: 10."
    )

    arg_parser.add_argument(
        "-m", "--parsing-method",
        type=ParsingMethod,
        default=ParsingMethod.PLASTEX,
        dest="parsing_method",
        help="Parsing backend: plasTeX (default) or regex. Only used for statements focus."
    )

    arg_parser.add_argument(
        "-v", "--validation-level",
        type=StatementValidationLevel,
        default=StatementValidationLevel.Paper,
        dest="validation_level",
        help="Validation strictness: paper (default) or statement. Only used for statements focus."
    )

    arg_parser.add_argument(
        "--shard",
        type=int,
        default=0,
        help="0-based shard index for this job. Use with --n-shards for array jobs. Default: 0."
    )

    arg_parser.add_argument(
        "--n-shards",
        type=int,
        default=1,
        dest="n_shards",
        help="Total number of shards (sbatch array size). Default: 1 (no sharding)."
    )

    arg_parser.add_argument(
        "--timings",
        action="store_true",
        help="Print timing for each database operation."
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
        focus=args.focus,
        context=args.context,
        overwrite=args.overwrite,
        batch_size=args.batch_size,
        workers=args.workers,
        timeout=args.timeout,
        parsing_method=args.parsing_method,
        validation_level=args.validation_level,
        shard=args.shard,
        n_shards=args.n_shards,
        timings=args.timings,
    )
