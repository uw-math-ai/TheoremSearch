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


def _process_one_file(conn, path: str, batch_size: int) -> dict:
    label = Path(path).stem  # e.g. "000", "001"
    print(f"\nBatch {label}")

    # Phase 1: parse + DB lookup (batched, flushed every batch_size statements)
    stmts_by_paper: Dict[str, List[dict]] = defaultdict(list)
    total_in = total_out = 0
    api_stats: dict = {}
    ok_parse = total_parse = 0
    buf_ids:     List[str]        = []
    buf_results: Dict[str, dict]  = {}

    def flush():
        meta_map = _fetch_stmts_by_id(conn, buf_ids)
        for sid in buf_ids:
            if sid in meta_map:
                meta = meta_map[sid]
                stmts_by_paper[meta["paper_id"]].append({**meta, **buf_results[sid]})
        buf_ids.clear()
        buf_results.clear()

    with tqdm(desc="  parse", unit=" stmts", dynamic_ncols=True) as pbar:
        for statement_id, text, usage in iter_batch_results([path], stats=api_stats):
            result = parse_extraction(text)
            total_parse += 1
            if result.get("defines") or result.get("uses"):
                ok_parse += 1
            total_in  += usage.get("prompt_tokens", 0)
            total_out += usage.get("completion_tokens", 0)
            buf_ids.append(statement_id)
            buf_results[statement_id] = result
            if len(buf_ids) >= batch_size:
                flush()
            pct = 100.0 * ok_parse / total_parse if total_parse else 0.0
            pbar.update()
            pbar.set_postfix({"ok": f"{pct:.1f}%", "api_skip": api_stats.get("skipped", 0)})
        flush()  # remaining statements

    parse_pct = 100.0 * ok_parse / total_parse if total_parse else 0.0

    paper_ids        = list(stmts_by_paper.keys())
    all_ids_by_paper = _fetch_all_paper_stmt_ids(conn, paper_ids)

    # Phase 3: connect
    total_deps = total_notations = failed = 0
    with tqdm(total=len(paper_ids), desc="  connect", dynamic_ncols=True, unit=" papers") as pbar:
        for pid in paper_ids:
            try:
                stmts   = sorted(stmts_by_paper[pid], key=lambda s: s["ordinal"])
                all_ids = all_ids_by_paper.get(pid, [s["statement_id"] for s in stmts])
                deps, notations  = _write_paper_deps(conn, all_ids, stmts)
                total_deps      += deps
                total_notations += notations
            except Exception as e:
                failed += 1
                print(f"\n[error] paper {pid}: {e}", file=sys.stderr)
            pbar.update()
            pbar.set_postfix({
                "ok": f"{parse_pct:.1f}%",
                "deps": total_deps,
                "notations": total_notations,
                "failed": failed,
            })

    return {
        "deps": total_deps, "notations": total_notations, "failed": failed,
        "total_in": total_in, "total_out": total_out,
    }


def connect_batch_results(conn, paths: List[str], batch_size: int) -> dict:
    totals: dict = {"deps": 0, "notations": 0, "failed": 0, "total_in": 0, "total_out": 0}
    for path in paths:
        stats = _process_one_file(conn, path, batch_size)
        for k in totals:
            totals[k] += stats[k]
    return totals


if __name__ == "__main__":
    parser = ArgumentParser(description="Write notation batch results to the database.")
    parser.add_argument("-i", "--input", type=str, nargs="+", default=None, dest="input_paths",
                        help=f"Results JSONL file(s) or S3 dir (default: {_default_output_dir()}).")
    parser.add_argument("-b", "--batch-size", type=int, default=256, dest="batch_size",
                        help="Chunk size for DB lookups (default: 256).")
    parser.add_argument("--shard", type=int, default=0, dest="shard_index",
                        help="0-based shard index for this node (default: 0).")
    parser.add_argument("--n-shards", type=int, default=1, dest="n_shards",
                        help="Total number of shards across all nodes (default: 1).")

    args = parser.parse_args()

    if args.input_paths:
        input_paths = args.input_paths
    else:
        output_dir  = _default_output_dir()
        input_paths = list_files(output_dir)
        if not input_paths:
            print(f"No result files found in {output_dir}.")
            sys.exit(1)

    input_paths = sorted(input_paths)
    if args.n_shards > 1:
        input_paths = input_paths[args.shard_index::args.n_shards]
        if not input_paths:
            print(f"Shard {args.shard_index}/{args.n_shards}: no files assigned.")
            sys.exit(0)

    print_script_header(
        action="Connecting notation batch results",
        params={
            "input":      args.input_paths or _default_output_dir(),
            "batch size": args.batch_size,
            **( {"shard": f"{args.shard_index}/{args.n_shards}"} if args.n_shards > 1 else {} ),
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
