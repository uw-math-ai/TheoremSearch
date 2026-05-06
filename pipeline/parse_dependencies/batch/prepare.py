"""
Phase 1: Generate JSONL batch for Nebius batch inference.

--method llm:   one request per statement  (custom_id = statement_id)
--method judge: one request per paper      (custom_id = paper_id)

Usage:
    python -m pipeline.parse_dependencies --method llm   --batch prepare -m qwen3-235b
    python -m pipeline.parse_dependencies --method judge --batch prepare -m deepseek-r1
"""

import json
from argparse import ArgumentParser
from pathlib import Path
from typing import Union

from jinja2 import Environment, FileSystemLoader
from tqdm import tqdm

from rds.utils.connect import get_rds_connection
from rds.utils.query import build_query, get_query_count
from rds.utils.paginate import paginate_query
from s3.utils.io import clear_folder, indexed_path, open_output, finalize_output
from ...printing import print_script_header
from ..write import _fetch_paper_statements, _papers_already_processed
from ..models import load_model_config

_S3_BUCKET = "dependency-graph-bucket"

_S3_FOLDERS = {
    "llm":   "notation_batches",
    "judge": "judge_batches",
}

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _s3_input_dir(method: str) -> str:
    return f"s3://{_S3_BUCKET}/{_S3_FOLDERS[method]}/input/"


def _s3_output_dir(method: str) -> str:
    return f"s3://{_S3_BUCKET}/{_S3_FOLDERS[method]}/output/"


def _state_path(method: str) -> Path:
    return Path(f".{method}_batch.run_state.json")


def _jinja_env():
    return Environment(
        loader=FileSystemLoader(_PROMPTS_DIR),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def _llm_request(stmt: dict, model_config: dict, template) -> dict:
    return {
        "custom_id": str(stmt["statement_id"]),
        "method":    "POST",
        "url":       "/v1/chat/completions",
        "body": {
            "model":      model_config["id"],
            "messages":   [{"role": "user", "content": template.render(statement=stmt)}],
            "max_tokens": model_config.get("max_tokens", 512),
        },
    }


def _judge_request(paper_id: str, paper_info: dict, statements: list,
                   model_config: dict, system_prompt: str) -> dict:
    from ..judge import _build_user_message
    user_msg = _build_user_message(paper_info, statements)
    return {
        "custom_id": paper_id,
        "method":    "POST",
        "url":       "/v1/chat/completions",
        "body": {
            "model":      model_config["id"],
            "messages":   [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_msg},
            ],
            "max_tokens": model_config.get("max_tokens", 16384),
        },
    }


def _judge_papers_already_processed(conn, paper_ids: list) -> set:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT s.paper_id::text
            FROM informal_dependency d
            JOIN statement s ON s.statement_id = d.src_id
            WHERE s.paper_id = ANY(%s::uuid[])
              AND d.cite_key IS NULL AND 'judge' = ANY(d.methods)
            """,
            (paper_ids,),
        )
        return {row[0] for row in cur.fetchall()}


def prepare_batch(
    method: str,
    output: Union[str, Path],
    model_config: dict,
    condition, condition_params,
    overwrite: bool,
    batch_size: int,
    shard: int, n_shards: int,
    sample: int = -1,
    rows_per_file: int = -1,
):
    output_str = str(output)
    is_dir     = output_str.endswith("/")
    splitting  = rows_per_file > 0

    if is_dir and output_str.startswith("s3://"):
        print(f"Clearing {output_str} ...")
        clear_folder(output_str)

    conn = get_rds_connection("v2")

    # Load method-specific assets
    if method == "llm":
        template = _jinja_env().get_template("notation.j2")
        system_prompt = None
    else:
        template = None
        system_prompt = (_PROMPTS_DIR / "intrapaper_judge_system.j2").read_text()

    query, params = build_query(
        sample=sample,
        base_query="SELECT paper.paper_id FROM paper",
        where_clauses=[
            {
                "if":        True,
                "condition": "EXISTS (SELECT 1 FROM statement WHERE statement.paper_id = paper.paper_id)",
            },
            {"if": bool(condition), "condition": condition or "", "params": condition_params},
            {
                "if":        n_shards > 1,
                "condition": "ABS(hashtext(paper.paper_id::text)) %% %s = %s",
                "params":    [n_shards, shard],
            },
        ],
    )

    total = get_query_count(conn, query, params)
    skipped = written = 0
    file_index   = 0
    rows_in_file = 0
    current_dest  = indexed_path(output_str, file_index) if (splitting or is_dir) else output_str
    current_local, f_out = open_output(current_dest)

    _already_done_fn = (
        _papers_already_processed if method == "llm"
        else _judge_papers_already_processed
    )

    with tqdm(total=total, dynamic_ncols=True, unit=" papers", desc="Preparing") as pbar:
        for page in paginate_query(conn, base_query=query, base_params=params,
                                   order_by="paper_id", page_size=batch_size):
            paper_ids = [str(p["paper_id"]) for p in page]

            if not overwrite:
                already_done = _already_done_fn(conn, paper_ids)
                to_process   = [pid for pid in paper_ids if pid not in already_done]
                skipped     += len(paper_ids) - len(to_process)
                paper_ids    = to_process

            if paper_ids:
                if method == "llm":
                    stmts_by_paper = _fetch_paper_statements(conn, paper_ids)
                    for pid in paper_ids:
                        for stmt in stmts_by_paper.get(pid, []):
                            req = _llm_request(stmt, model_config, template)
                            _write_row(f_out, req, splitting, rows_per_file,
                                       output_str, file_index, rows_in_file, current_dest, current_local)
                            written      += 1
                            rows_in_file += 1
                            if splitting and rows_in_file >= rows_per_file:
                                finalize_output(f_out, current_local, current_dest)
                                file_index   += 1
                                rows_in_file  = 0
                                current_dest  = indexed_path(output_str, file_index)
                                current_local, f_out = open_output(current_dest)
                else:
                    # judge: one request per paper
                    stmts_by_paper = _fetch_judge_statements(conn, paper_ids)
                    paper_info_map = _fetch_paper_info(conn, paper_ids)
                    for pid in paper_ids:
                        stmts = stmts_by_paper.get(pid, [])
                        if not stmts:
                            continue
                        paper_info = paper_info_map.get(pid, {})
                        req = _judge_request(pid, paper_info, stmts,
                                             model_config, system_prompt)
                        f_out.write(json.dumps(req, ensure_ascii=False) + "\n")
                        written      += 1
                        rows_in_file += 1
                        if splitting and rows_in_file >= rows_per_file:
                            finalize_output(f_out, current_local, current_dest)
                            file_index   += 1
                            rows_in_file  = 0
                            current_dest  = indexed_path(output_str, file_index)
                            current_local, f_out = open_output(current_dest)

            pbar.update(len(page))
            pbar.set_postfix({"written": written, "skipped": skipped})

    finalize_output(f_out, current_local, current_dest)
    n_files = file_index + 1
    dest_display = (output_str if is_dir
                    else indexed_path(output_str, 0).replace("_0000", "_*") if splitting
                    else current_dest)
    print(f"\nDone. {written} requests in {n_files} file(s) → {dest_display}, {skipped} papers skipped.")


def _write_row(f_out, req, splitting, rows_per_file, output_str, file_index, rows_in_file, current_dest, current_local):
    f_out.write(json.dumps(req, ensure_ascii=False) + "\n")


def _fetch_judge_statements(conn, paper_ids: list) -> dict:
    from collections import defaultdict
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.statement_id, s.paper_id, s.kind, im.ref, im.note,
                   s.body, s.proof, im.pre_context, im.post_context
            FROM statement s
            JOIN informal_metadata im ON im.statement_id = s.statement_id
            WHERE s.paper_id = ANY(%s::uuid[])
            ORDER BY s.paper_id, im.ordinal
            """,
            (paper_ids,),
        )
        rows = cur.fetchall()
    stmts: dict = defaultdict(list)
    for row in rows:
        d = dict(zip(["statement_id", "paper_id", "kind", "ref", "note",
                      "body", "proof", "pre_context", "post_context"], row))
        d["statement_id"] = str(d["statement_id"])
        d["paper_id"]     = str(d["paper_id"])
        stmts[d["paper_id"]].append(d)
    return stmts


def _fetch_paper_info(conn, paper_ids: list) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.paper_id::text, p.title, apm.abstract
            FROM paper p
            LEFT JOIN arxiv_paper_metadata apm ON apm.arxiv_id = p.external_id
            WHERE p.paper_id = ANY(%s::uuid[])
            """,
            (paper_ids,),
        )
        return {
            row[0]: {"title": row[1] or "", "abstract": row[2] or ""}
            for row in cur.fetchall()
        }


if __name__ == "__main__":
    parser = ArgumentParser(description="Generate dependency JSONL batch for Nebius.")
    parser.add_argument("-M", "--method", required=True, choices=["llm", "judge"])
    parser.add_argument("-m", "--model", required=True, dest="model_name",
                        help="Short model alias from models.json (e.g. qwen3-235b).")
    parser.add_argument("-o", "--output", type=str, default=None)
    parser.add_argument("-c", "--condition", type=str, nargs="+", metavar=("SQL", "PARAM"))
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("-b", "--batch-size", type=int, default=64, dest="batch_size")
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--n-shards", type=int, default=1, dest="n_shards")
    parser.add_argument("--sample", type=int, default=-1)
    parser.add_argument("--rows-per-file", type=int, default=-1, dest="rows_per_file")

    args = parser.parse_args()

    if args.condition and len(args.condition) >= 2:
        condition, *condition_params = args.condition
    else:
        condition        = args.condition[0] if args.condition else None
        condition_params = []

    model_config = load_model_config(args.model_name)
    output       = args.output or _s3_input_dir(args.method)

    print_script_header(
        action=f"Preparing {args.method} batch",
        params={
            "method":     args.method,
            "model":      args.model_name,
            "output":     output,
            "condition?": condition,
            "params?":    condition_params or None,
            "overwrite":  args.overwrite,
            "batch size": args.batch_size,
            "shard?":     f"{args.shard}/{args.n_shards}" if args.n_shards > 1 else None,
            "sample?":    args.sample if args.sample > 0 else None,
            "rows/file?": args.rows_per_file if args.rows_per_file > 0 else None,
        },
    )

    prepare_batch(
        method=args.method,
        output=output,
        model_config=model_config,
        condition=condition,
        condition_params=condition_params,
        overwrite=args.overwrite,
        batch_size=args.batch_size,
        shard=args.shard,
        n_shards=args.n_shards,
        sample=args.sample,
        rows_per_file=args.rows_per_file,
    )
