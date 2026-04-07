from tqdm import tqdm
from typing import List, Optional
from datetime import datetime, timezone
from concurrent.futures import ProcessPoolExecutor, as_completed
from argparse import ArgumentParser
from arXiTeX.types import StatementValidationLevel, ParsingMethod
from arXiTeX import parse_paper
from rds.utils.connect import get_rds_connection
from rds.utils.query import build_query, get_query_count
from rds.utils.paginate import paginate_query
from rds.utils.upsert import upsert_rows
from ..printing import print_script_header

STATEMENT_KINDS = [
    "theorem", "lemma", "proposition", "corollary",
    "definition",
    "axiom", "postulate",
    "conjecture", "hypothesis",
    "remark", "note", "observation",
    "claim",
    "fact",
    "assumption",
    "notation", "convention"
]

def _fetch_existing_statements(cur, paper_id: str) -> list[dict]:
    """
    Return all existing statements + informal_metadata for *paper_id*.
    Each row: {statement_id, kind, body, ref, label, note}
    """
    cur.execute(
        """
        SELECT s.statement_id, s.kind, s.body,
               im.ref, im.label, im.note
        FROM statement s
        LEFT JOIN informal_metadata im USING (statement_id)
        WHERE s.paper_id = %s AND s.formality = 'informal'
        """,
        (paper_id,),
    )
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _fix_refs_for_paper(cur, paper_id: str, statements, ref_counts: dict) -> None:
    """
    For each newly parsed statement, try to find an existing DB row that
    matches on kind + label + body (all three must match).  On a match,
    update ref in informal_metadata.  On no match, insert as a new statement.

    ref_counts is mutated: {"seen": n, "updated": n}
    """
    existing = _fetch_existing_statements(cur, paper_id)

    # Build a lookup: (kind, label, body) -> {statement_id, ref}.
    # First match wins for duplicates.
    existing_lookup: dict[tuple, dict] = {}
    for row in existing:
        key = (row["kind"], row["label"], row["body"])
        if key not in existing_lookup:
            existing_lookup[key] = {"statement_id": row["statement_id"], "ref": row["ref"]}

    for stmt in statements:
        ref_counts["seen"] += 1
        key = (stmt.kind, stmt.label, stmt.body)
        existing_row = existing_lookup.get(key)

        if existing_row is not None:
            if stmt.ref != existing_row["ref"]:
                cur.execute(
                    "UPDATE informal_metadata SET ref = %s WHERE statement_id = %s",
                    (stmt.ref, existing_row["statement_id"]),
                )
                ref_counts["updated"] += 1
        else:
            # No match — insert as new statement + metadata
            cur.execute(
                """
                INSERT INTO statement (paper_id, formality, kind, body, proof)
                VALUES (%s, 'informal', %s, %s, %s)
                RETURNING statement_id
                """,
                (paper_id, stmt.kind, stmt.body, stmt.proof),
            )
            new_id = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO informal_metadata (statement_id, ref, label, note)
                VALUES (%s, %s, %s, %s)
                """,
                (new_id, stmt.ref, stmt.label, stmt.note),
            )


def parse_papers(
    condition: str,
    condition_params: List[str],
    overwrite: bool,
    batch_size: int,
    workers: int,
    timeout: int,
    parsing_method: ParsingMethod,
    validation_level: StatementValidationLevel,
    source_from_s3: bool,
    fix_ref: bool = False,
):
    if timeout < 0:
        timeout = None

    print_script_header(
        action="Parsing papers into statements" + (" (fix-ref mode)" if fix_ref else ""),
        params={
            "condition?": condition,
            "condition params?": condition_params,
            "overwrite": overwrite,
            "fix-ref": fix_ref,
            "batch size": batch_size,
            "workers": workers,
            "timeout": timeout,
            "parsing method": parsing_method.value,
            "validation level": validation_level.value,
            "source": "arXiv S3 bucket" if source_from_s3 else "arXiv API"
        }
    )

    conn = get_rds_connection("v2")

    query, params = build_query(
        base_query="""
            SELECT paper.paper_id, s3_location.arxiv_id, s3_location.bundle_key, s3_location.bytes_range
            FROM paper
            INNER JOIN s3_location
            ON s3_location.arxiv_id = paper.external_id
        """ if source_from_s3 else "SELECT paper.paper_id, external_id as arxiv_id FROM paper",
        where_clauses=[
            {
                "if": not overwrite and not fix_ref,
                "condition": """
                    NOT EXISTS (
                        SELECT 1 from statement
                        WHERE statement.paper_id = paper.paper_id
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
                "condition": "paper.kind = 'paper'"
            }
        ]
    )

    paper_count = get_query_count(conn, query, params)

    status_counts = {
        "success": 0,
        "failed": 0
    }
    ref_counts = {"seen": 0, "updated": 0}

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

            current_time = datetime.now(timezone.utc)

            for paper in papers:
                paper_id = paper["paper_id"]
                arxiv_id = paper["arxiv_id"]

                s3_bundle_key = paper.get("bundle_key", None)
                s3_bytes_range = paper.get("bytes_range", None)

                fut = ex.submit(
                    parse_paper,
                    arxiv_id,
                    s3_bundle_key,
                    s3_bytes_range,
                    None,
                    ["proof", *STATEMENT_KINDS],
                    parsing_method,
                    validation_level,
                    None
                )
                fut_to_paper[fut] = {"paper_id": paper_id, "arxiv_id": arxiv_id}

            for fut in as_completed(fut_to_paper):
                paper_id = fut_to_paper[fut]["paper_id"]
                arxiv_id = fut_to_paper[fut]["arxiv_id"]
                error = None

                try:
                    statements = fut.result()

                    if not statements:
                        raise RuntimeError() # this shouldn't happen
                except Exception as e:
                    error = str(e) or "[UNHANDLED ERROR]"
                    statements = None

                if not statements:
                    status_counts["failed"] += 1
                else:
                    status_counts["success"] += 1

                batch_parse_status_rows.append({
                    "arxiv_id": arxiv_id,
                    "last_parse_attempt_at": current_time,
                    "error": error,
                    "s3": source_from_s3,
                    "parsing_method": parsing_method.value,
                    "validation_level": validation_level.value
                })

                if statements:
                    if fix_ref:
                        with conn.cursor() as cur:
                            _fix_refs_for_paper(cur, paper_id, statements, ref_counts)
                    else:
                        batch_statement_rows.extend([
                            {
                                "paper_id": paper_id,
                                "formality": "informal",
                                "kind": statement.kind,
                                "body": statement.body,
                                "proof": statement.proof
                            }
                            for statement in statements
                        ])

                        batch_informal_metadata_rows.extend([
                            {
                                "ref": statement.ref,
                                "label": statement.label,
                                "note": statement.note
                            }
                            for statement in statements
                        ])

                pbar.update()

                parse_attempts = sum(status_counts.values())

                postfix = {
                    status: f"{(100.0 * count / parse_attempts):.2f}%"
                    for status, count in status_counts.items()
                }
                if fix_ref:
                    postfix["stmts"] = ref_counts["seen"]
                    postfix["updated"] = ref_counts["updated"]
                pbar.set_postfix(postfix)

            upsert_rows(
                conn,
                table="arxiv_parse_status",
                rows=batch_parse_status_rows,
                on_conflict={
                    "with": ["arxiv_id"],
                    "replace": ["last_parse_attempt_at", "error", "s3", "parsing_method", "validation_level"]
                }
            )

            if not fix_ref and batch_statement_rows:
                paper_ids = list({row["paper_id"] for row in batch_statement_rows})

                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM statement WHERE paper_id::TEXT = ANY(%s)",
                        (paper_ids,),
                    )

                    # Insert statement rows and collect generated statement_ids,
                    # keeping order in sync with batch_informal_metadata_rows.
                    inserted_ids = []
                    for row in batch_statement_rows:
                        cur.execute(
                            """
                            INSERT INTO statement (paper_id, formality, kind, body, proof)
                            VALUES (%(paper_id)s, %(formality)s, %(kind)s, %(body)s, %(proof)s)
                            RETURNING statement_id
                            """,
                            row,
                        )
                        inserted_ids.append(cur.fetchone()[0])

                    cur.executemany(
                        """
                        INSERT INTO informal_metadata (statement_id, ref, label, note)
                        VALUES (%(statement_id)s, %(ref)s, %(label)s, %(note)s)
                        """,
                        [
                            {"statement_id": sid, **meta}
                            for sid, meta in zip(inserted_ids, batch_informal_metadata_rows)
                        ],
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
        help="Whether to overwrite statements from previously parsed papers. By default, False"
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
        "-m",
        "--parsing_method",
        type=ParsingMethod,
        default=ParsingMethod.PLASTEX,
        help="Method to parse"
    )

    arg_parser.add_argument(
        "-v",
        "--validation-level",
        type=StatementValidationLevel,
        required=False,
        default=StatementValidationLevel.Paper,
        help="Level to validate statements. Supported: paper (default), statement"
    )

    arg_parser.add_argument(
        "-s3",
        "--source-from-s3",
        action="store_true",
        help="Whether to source paper sources from S3. By default, API"
    )

    arg_parser.add_argument(
        "--fix-ref",
        action="store_true",
        help=(
            "Fix-ref mode: match newly parsed statements to existing DB rows by "
            "kind + label + body, updating only the ref. Unmatched statements are "
            "inserted as new. Existing unmatched rows are left untouched."
        )
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
        parsing_method=args.parsing_method,
        validation_level=args.validation_level,
        source_from_s3=args.source_from_s3,
        fix_ref=args.fix_ref,
    )