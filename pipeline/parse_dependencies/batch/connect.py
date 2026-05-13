"""
Phase 4: Read Nebius batch results and write deps to the database.

--method llm:   custom_id = statement_id → group by paper → match_paper → write
--method judge: custom_id = paper_id    → parse judge JSON → write

Usage:
    python -m pipeline.parse_dependencies --method llm   --batch connect
    python -m pipeline.parse_dependencies --method judge --batch connect
    python -m pipeline.parse_dependencies --method llm   --batch connect -i results.jsonl
"""

import re
import sys
from argparse import ArgumentParser
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from tqdm import tqdm

from rds.utils.connect import get_rds_connection
from rds.utils.upsert import upsert_rows
from s3.utils.io import list_files
from s3.utils.batch import iter_batch_results
from ...printing import print_script_header
from ..extract import parse_extraction_batch
from ..write import _write_paper_deps
from .prepare import _s3_output_dir, _fetch_judge_statements, _fetch_paper_info

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _default_output_dir(method: str) -> str:
    return _s3_output_dir(method)


# ------------------------------------------------------------------ #
# LLM connect helpers                                                  #
# ------------------------------------------------------------------ #

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


def _process_llm_file(conn, path: str, batch_size: int) -> dict:
    label = Path(path).stem
    print(f"\nBatch {label}")

    stmts_by_paper: Dict[str, List[dict]] = defaultdict(list)
    total_in = total_out = 0
    api_stats: dict = {}
    ok_parse = total_parse = 0
    buf_ids:     List[str]       = []
    buf_results: Dict[str, dict] = {}

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
            extractions = parse_extraction_batch(text, expected_ids=[statement_id])
            result = extractions.get(statement_id) or {"defines": [], "uses": []}
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
        flush()

    parse_pct = 100.0 * ok_parse / total_parse if total_parse else 0.0
    paper_ids        = list(stmts_by_paper.keys())
    all_ids_by_paper = _fetch_all_paper_stmt_ids(conn, paper_ids)

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


# ------------------------------------------------------------------ #
# Judge connect helpers                                                #
# ------------------------------------------------------------------ #

def _process_judge_file(conn, path: str, batch_size: int) -> dict:
    from ..judge import _parse_judge_json
    label = Path(path).stem
    print(f"\nBatch {label}")

    paper_results: List[tuple] = []  # (paper_id, text, usage)
    api_stats: dict = {}
    total_in = total_out = 0

    with tqdm(desc="  parse", unit=" papers", dynamic_ncols=True) as pbar:
        for paper_id, text, usage in iter_batch_results([path], stats=api_stats):
            paper_results.append((paper_id, text, usage))
            total_in  += usage.get("prompt_tokens", 0)
            total_out += usage.get("completion_tokens", 0)
            pbar.update()
            pbar.set_postfix({"api_skip": api_stats.get("skipped", 0)})

    paper_ids = [r[0] for r in paper_results]
    stmts_by_paper = _fetch_judge_statements(conn, paper_ids)

    total_deps = failed = 0
    with tqdm(total=len(paper_results), desc="  connect", dynamic_ncols=True, unit=" papers") as pbar:
        for paper_id, text, _ in paper_results:
            stmts = stmts_by_paper.get(paper_id, [])
            if not stmts:
                failed += 1
                pbar.update()
                continue
            text = _THINK_RE.sub("", text).strip()
            valid_ids = {str(s["statement_id"]) for s in stmts}
            rows = _parse_judge_json(text, valid_ids)
            if rows is None:
                tqdm.write(f"[judge] failed to parse response for {paper_id}: {text[:200]}")
                failed += 1
                pbar.update()
                continue
            stmt_ids = [s["statement_id"] for s in stmts]
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM informal_dependency"
                    " WHERE cite_key IS NULL AND methods = ARRAY['judge'] AND src_id = ANY(%s::uuid[])",
                    (stmt_ids,),
                )
            if rows:
                upsert_rows(conn, "informal_dependency", rows)
            conn.commit()
            total_deps += len(rows)
            pbar.update()
            pbar.set_postfix({"deps": total_deps, "failed": failed})

    return {
        "deps": total_deps, "notations": 0, "failed": failed,
        "total_in": total_in, "total_out": total_out,
    }


# ------------------------------------------------------------------ #
# Top-level                                                            #
# ------------------------------------------------------------------ #

def connect_batch_results(conn, method: str, paths: List[str], batch_size: int) -> dict:
    process_fn = _process_llm_file if method == "llm" else _process_judge_file
    totals: dict = {"deps": 0, "notations": 0, "failed": 0, "total_in": 0, "total_out": 0}
    for path in paths:
        stats = process_fn(conn, path, batch_size)
        for k in totals:
            totals[k] += stats[k]
    return totals


if __name__ == "__main__":
    parser = ArgumentParser(description="Write batch results to the database.")
    parser.add_argument("-M", "--method", required=True, choices=["llm", "judge"])
    parser.add_argument("-i", "--input", type=str, nargs="+", default=None, dest="input_paths")
    parser.add_argument("-b", "--batch-size", type=int, default=256, dest="batch_size")
    parser.add_argument("--shard", type=int, default=0, dest="shard_index")
    parser.add_argument("--n-shards", type=int, default=1, dest="n_shards")

    args = parser.parse_args()

    if args.input_paths:
        input_paths = args.input_paths
    else:
        output_dir  = _default_output_dir(args.method)
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
        action=f"Connecting {args.method} batch results",
        params={
            "input":      args.input_paths or _default_output_dir(args.method),
            "batch size": args.batch_size,
            **({"shard": f"{args.shard_index}/{args.n_shards}"} if args.n_shards > 1 else {}),
        },
    )

    conn  = get_rds_connection("v2")
    stats = connect_batch_results(conn, args.method, input_paths, args.batch_size)

    extra = f", {stats['notations']} notations" if args.method == "llm" else ""
    print(
        f"\nDone. {stats['deps']} deps{extra} written ({stats['failed']} papers failed)."
        f"\n  Input tokens:  {stats['total_in']:,}"
        f"\n  Output tokens: {stats['total_out']:,}"
    )
