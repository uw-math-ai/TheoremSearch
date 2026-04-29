"""
Phase 2: Read Nebius batch results and write notation deps to the database.

Each result line has custom_id = statement_id. This phase looks up statement
metadata from the DB, groups by paper, and writes deps + notation via _write_paper_deps.

Run:
    python -m pipeline.parse_notations.batch.connect
    python -m pipeline.parse_notations.batch.connect -i results.jsonl
    python -m pipeline.parse_notations.batch.connect -i s3://bucket/notation_batches/output/results.jsonl
"""

import sys
from argparse import ArgumentParser
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from tqdm import tqdm

from rds.utils.connect import get_rds_connection
from s3.utils.io import list_files
from s3.utils.batch import iter_batch_results
from ...printing import print_script_header
from ..extract import parse_extraction
from ..write import _write_paper_deps
from .prepare import _S3_BUCKET, _S3_FOLDER


def _default_output_dir() -> str:
    return f"s3://{_S3_BUCKET}/{_S3_FOLDER}/output/"


def _fetch_stmts_by_id(conn, statement_ids: List[str]) -> Dict[str, dict]:
    if not statement_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.statement_id, s.paper_id, s.kind, im.note, s.body, s.proof, im.ordinal
            FROM statement s
            JOIN informal_metadata im ON im.statement_id = s.statement_id
            WHERE s.statement_id = ANY(%s::uuid[])
            """,
            (statement_ids,),
        )
        rows = cur.fetchall()
    result = {}
    for row in rows:
        d = dict(zip(["statement_id", "paper_id", "kind", "note", "body", "proof", "ordinal"], row))
        d["statement_id"] = str(d["statement_id"])
        d["paper_id"]     = str(d["paper_id"])
        result[d["statement_id"]] = d
    return result


def _fetch_all_paper_stmt_ids(conn, paper_ids: List[str]) -> Dict[str, List[str]]:
    if not paper_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT statement_id::text, paper_id::text FROM statement"
            " WHERE paper_id = ANY(%s::uuid[])",
            (paper_ids,),
        )
        result: Dict[str, List[str]] = defaultdict(list)
        for sid, pid in cur.fetchall():
            result[pid].append(sid)
    return result


def connect_batch_results(conn, paths: List[str], batch_size: int) -> dict:
    # Step 1: parse all results from JSONL
    extractions: Dict[str, dict] = {}
    total_in = total_out = 0
    for statement_id, text, usage in iter_batch_results(paths):
        extractions[statement_id] = parse_extraction(text)
        total_in  += usage.get("prompt_tokens", 0)
        total_out += usage.get("completion_tokens", 0)

    print(f"Parsed {len(extractions)} statement results.")

    # Step 2: look up statement metadata from DB in chunks
    stmt_ids  = list(extractions.keys())
    stmts_meta: Dict[str, dict] = {}
    for i in range(0, len(stmt_ids), batch_size * 10):
        chunk = stmt_ids[i:i + batch_size * 10]
        stmts_meta.update(_fetch_stmts_by_id(conn, chunk))

    # Step 3: group by paper, merging extraction into metadata
    stmts_by_paper: Dict[str, List[dict]] = defaultdict(list)
    for sid, meta in stmts_meta.items():
        stmts_by_paper[meta["paper_id"]].append({**meta, **extractions[sid]})

    # Step 4: fetch ALL statement_ids per paper for the DELETE
    paper_ids        = list(stmts_by_paper.keys())
    all_ids_by_paper = _fetch_all_paper_stmt_ids(conn, paper_ids)

    # Step 5: write per paper
    total_deps = total_notations = failed = 0
    with tqdm(total=len(paper_ids), dynamic_ncols=True, unit=" papers") as pbar:
        for pid in paper_ids:
            try:
                stmts   = sorted(stmts_by_paper[pid], key=lambda s: s["ordinal"])
                all_ids = all_ids_by_paper.get(pid, [s["statement_id"] for s in stmts])
                deps, notations     = _write_paper_deps(conn, all_ids, stmts)
                total_deps         += deps
                total_notations    += notations
            except Exception as e:
                failed += 1
                print(f"\n[error] paper {pid}: {e}", file=sys.stderr)
            pbar.update()
            pbar.set_postfix({"deps": total_deps, "notations": total_notations, "failed": failed})

    return {
        "deps":      total_deps,
        "notations": total_notations,
        "failed":    failed,
        "total_in":  total_in,
        "total_out": total_out,
    }


if __name__ == "__main__":
    parser = ArgumentParser(description="Write notation batch results to the database.")
    parser.add_argument("-i", "--input", type=str, nargs="+", default=None, dest="input_paths",
                        help=f"Results JSONL file(s) or S3 dir (default: {_default_output_dir()}).")
    parser.add_argument("-b", "--batch-size", type=int, default=256, dest="batch_size",
                        help="Chunk size for DB lookups (default: 256).")

    args = parser.parse_args()

    if args.input_paths:
        input_paths = args.input_paths
    else:
        output_dir  = _default_output_dir()
        input_paths = list_files(output_dir)
        if not input_paths:
            print(f"No result files found in {output_dir}.")
            sys.exit(1)

    print_script_header(
        action="Connecting notation batch results",
        params={
            "input":      args.input_paths or _default_output_dir(),
            "batch size": args.batch_size,
        },
    )

    conn  = get_rds_connection("v2")
    stats = connect_batch_results(conn, input_paths, args.batch_size)

    print(
        f"\nDone. {stats['deps']} deps, {stats['notations']} notations written"
        f" ({stats['failed']} papers failed)."
        f"\n  Input tokens:  {stats['total_in']:,}"
        f"\n  Output tokens: {stats['total_out']:,}"
    )
