from tqdm import tqdm
from typing import List
from datetime import datetime, timezone
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
from argparse import ArgumentParser
import time
from psycopg2.extras import Json
from arXiTeX.types import StatementValidationLevel, ParsingMethod, ParseFocus
from arXiTeX import parse_paper
from rds.utils.connect import get_rds_connection
from rds.utils.query import build_query, get_query_count
from rds.utils.paginate import paginate_query
from rds.utils.upsert import upsert_rows, update_rows, insert_rows_returning
from ..printing import print_script_header

STATEMENT_KINDS = {
    "theorem", "lemma", "proposition", "corollary",
    "definition",
    "axiom", "postulate",
    "conjecture", "hypothesis",
    "remark", "note", "observation",
    "claim",
    "fact",
    "assumption",
    "notation", "convention",
    "criterion", "principle"
}


@contextmanager
def _timer(label: str, enabled: bool):
    if not enabled:
        yield
        return
    t = time.perf_counter()
    yield
    print(f"[timer] {label}: {time.perf_counter() - t:.3f}s")


def _overwrite_condition(focus: ParseFocus) -> str:
    """Returns a SQL condition (for WHERE) that filters out papers already processed
    under the given focus. Only applied when overwrite=False."""
    match focus:
        case ParseFocus.STATEMENTS:
            return """
                NOT EXISTS (
                    SELECT 1 FROM statement
                    WHERE statement.paper_id = paper.paper_id
                )
            """
        case ParseFocus.PREAMBLE:
            return """
                NOT EXISTS (
                    SELECT 1 FROM arxiv_paper_metadata
                    WHERE arxiv_id = paper.external_id AND preamble IS NOT NULL
                )
            """
        case ParseFocus.BIBLIOGRAPHY:
            return """
                NOT EXISTS (
                    SELECT 1 FROM arxiv_paper_metadata
                    WHERE arxiv_id = paper.external_id AND bibliography IS NOT NULL
                )
            """
        case ParseFocus.ALL:
            # Skip only when all three are already present
            return """
                NOT (
                    EXISTS (
                        SELECT 1 FROM statement
                        WHERE statement.paper_id = paper.paper_id
                    )
                    AND EXISTS (
                        SELECT 1 FROM arxiv_paper_metadata
                        WHERE arxiv_id = paper.external_id AND preamble IS NOT NULL
                    )
                    AND EXISTS (
                        SELECT 1 FROM arxiv_paper_metadata
                        WHERE arxiv_id = paper.external_id AND bibliography IS NOT NULL
                    )
                )
            """


def parse_papers(
    condition: str,
    condition_params: List[str],
    focus: ParseFocus,
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
            "condition?": condition,
            "condition params?": condition_params,
            "overwrite": overwrite,
            "batch size": batch_size,
            "workers": workers,
            "timeout": timeout,
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
            "SELECT paper.paper_id, external_id as arxiv_id FROM paper"
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
                "params": condition_params
            },
            {
                "if": True,
                "condition": "paper.kind = 'paper'"
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

    status_counts = {"success": 0, "failed": 0}

    pbar = tqdm(total=paper_count, dynamic_ncols=True)
    ex = ProcessPoolExecutor(max_workers=workers, max_tasks_per_child=50)

    with pbar, ex:
        for papers in paginate_query(
            conn,
            base_query=query,
            base_params=params,
            order_by="arxiv_id",
            page_size=batch_size
        ):
            fut_to_paper = {}
            batch_statement_rows = []
            batch_informal_metadata_rows = []
            batch_parse_status_rows = []
            batch_preamble_rows = []
            batch_bibliography_rows = []

            for paper in papers:
                paper_id = paper["paper_id"]
                arxiv_id = paper["arxiv_id"]

                fut = ex.submit(
                    parse_paper,
                    arxiv_id,
                    None, None, None,
                    STATEMENT_KINDS,
                    parsing_method,
                    validation_level,
                    timeout,
                    focus,
                )
                fut_to_paper[fut] = {"paper_id": paper_id, "arxiv_id": arxiv_id}

            for fut in as_completed(fut_to_paper):
                paper_id = fut_to_paper[fut]["paper_id"]
                arxiv_id = fut_to_paper[fut]["arxiv_id"]
                current_time = datetime.now(timezone.utc)
                error = None
                result = None

                try:
                    result = fut.result()

                    if do_statements and not result.statements:
                        raise RuntimeError()  # this shouldn't happen
                except Exception as e:
                    error = str(e) or "[UNHANDLED ERROR]"
                    result = None

                if result is None:
                    status_counts["failed"] += 1
                else:
                    status_counts["success"] += 1

                if do_statements:
                    batch_parse_status_rows.append({
                        "arxiv_id": arxiv_id,
                        "last_parse_attempt_at": current_time,
                        "error": error,
                        "parsing_method": parsing_method.value,
                        "validation_level": validation_level.value,
                    })

                if result is not None:
                    if result.statements:
                        batch_statement_rows.extend([
                            {
                                "paper_id": paper_id,
                                "formality": "informal",
                                "kind": statement.kind,
                                "body": statement.body,
                                "proof": statement.proof
                            }
                            for statement in result.statements
                        ])

                        batch_informal_metadata_rows.extend([
                            {
                                "ref": statement.ref,
                                "label": statement.label,
                                "note": statement.note
                            }
                            for statement in result.statements
                        ])

                    if result.preamble is not None:
                        batch_preamble_rows.append({"arxiv_id": arxiv_id, "preamble": result.preamble})
                    if result.bibliography:
                        batch_bibliography_rows.append({"arxiv_id": arxiv_id, "bibliography": Json(result.bibliography), "bibtex": result.bibliography_bibtex})

                pbar.update()

                parse_attempts = sum(status_counts.values())
                pbar.set_postfix({
                    status: f"{(100.0 * count / parse_attempts):.2f}%"
                    for status, count in status_counts.items()
                })

            if batch_parse_status_rows:
                with _timer("upsert arxiv_parse_status", timings):
                    upsert_rows(
                        conn,
                        table="arxiv_parse_status",
                        rows=batch_parse_status_rows,
                        on_conflict={
                            "with": ["arxiv_id"],
                            "replace": ["last_parse_attempt_at", "error", "parsing_method", "validation_level"]
                        }
                    )

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

            if batch_preamble_rows:
                with _timer("update arxiv_paper_metadata (preamble)", timings):
                    update_rows(
                        conn,
                        table="arxiv_paper_metadata",
                        rows=batch_preamble_rows,
                        where=["arxiv_id"],
                    )

            if batch_bibliography_rows:
                with _timer("update arxiv_paper_metadata (bibliography)", timings):
                    update_rows(
                        conn,
                        table="arxiv_paper_metadata",
                        rows=batch_bibliography_rows,
                        where=["arxiv_id"],
                        casts={"bibliography": "jsonb"},
                    )

            with _timer("commit", timings):
                conn.commit()

            pbar.update(0)  # flush postfix


if __name__ == "__main__":
    arg_parser = ArgumentParser(
        description="Parse arXiv papers and store results in the database."
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
