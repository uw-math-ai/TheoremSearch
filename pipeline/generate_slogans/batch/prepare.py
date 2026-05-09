"""
Phase 1: Generate per-statement slogan JSONL batch for Nebius batch inference.

Each request renders a prompt template for one statement. custom_id = statement_id
so Phase 3 (connect) can write results back using only that key.

Run:
    python -m pipeline.generate_slogans.batch.prepare -p context-0 -m qwen3-235b
    python -m pipeline.generate_slogans.batch.prepare -p context-0 -m qwen3-235b -o s3://bucket/slogan_batches/input/
    python -m pipeline.generate_slogans.batch.prepare -p context-0 -m qwen3-235b -c "paper.kind = 'paper'"
"""

import json
from argparse import ArgumentParser
from pathlib import Path
from typing import Union

from tqdm import tqdm

from rds.utils.connect import get_rds_connection
from rds.utils.query import build_query, get_query_count
from rds.utils.paginate import paginate_query
from s3.utils.io import clear_folder, indexed_path, open_output, finalize_output
from ...printing import print_script_header
from ..prompt_utils import (
    load_prompt, load_model_config,
    detect_needed_joins, fetch_contexts, render_prompt,
    condition_joins,
)

_S3_BUCKET = "dependency-graph-bucket"
_S3_FOLDER = "slogan_batches"


def _batch_subfolder(model_name: str, prompt_name: str) -> str:
    """Per-pair subfolder, so multiple (model, prompt) batches don't collide."""
    return f"{model_name}+{prompt_name}"


def _default_input_dir(model_name: str, prompt_name: str) -> str:
    return f"s3://{_S3_BUCKET}/{_S3_FOLDER}/{_batch_subfolder(model_name, prompt_name)}/input/"


def _default_output_dir(model_name: str, prompt_name: str) -> str:
    return f"s3://{_S3_BUCKET}/{_S3_FOLDER}/{_batch_subfolder(model_name, prompt_name)}/output/"


def _state_path(model_name: str, prompt_name: str) -> Path:
    return Path(f".slogan_batch.{_batch_subfolder(model_name, prompt_name)}.run_state.json")


def _build_request(statement_id: str, prompt_text: str, model_config: dict) -> dict:
    return {
        "custom_id": statement_id,
        "method":    "POST",
        "url":       "/v1/chat/completions",
        "body": {
            "model":       model_config["model"],
            "messages":    [{"role": "user", "content": prompt_text}],
            "temperature": model_config.get("temperature", 0.7),
            "max_tokens":  model_config.get("max_tokens", 512),
        },
    }


def prepare_batch(
    output: Union[str, Path],
    prompt_name: str,
    model_name: str,
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

    spec         = load_prompt(prompt_name)
    model_config = load_model_config(model_name)
    joins        = detect_needed_joins(spec.source)

    if is_dir and output_str.startswith("s3://"):
        print(f"Clearing {output_str} ...")
        clear_folder(output_str)

    conn = get_rds_connection("v2")

    base_query = "SELECT statement.statement_id FROM statement" + condition_joins(condition)

    query, params = build_query(
        sample=sample,
        base_query=base_query,
        where_clauses=[
            {
                "if": not overwrite,
                "condition": """
                    NOT EXISTS (
                        SELECT 1 FROM slogan
                        WHERE slogan.statement_id = statement.statement_id
                          AND slogan.prompt_name = %s
                          AND slogan.model_name = %s
                    )
                """,
                "params": [spec.name, model_name],
            },
            {
                "if": bool(condition),
                "condition": condition or "",
                "params": condition_params,
            },
            {
                "if": n_shards > 1,
                "condition": "ABS(hashtext(statement.statement_id::text)) %% %s = %s",
                "params": [n_shards, shard],
            },
        ],
    )

    total = get_query_count(conn, query, params)
    skipped = written = 0
    file_index   = 0
    rows_in_file = 0
    current_dest  = indexed_path(output_str, file_index) if (splitting or is_dir) else output_str
    current_local, f_out = open_output(current_dest)

    with tqdm(total=total, dynamic_ncols=True, unit=" statements", desc="Preparing") as pbar:
        for page in paginate_query(conn, base_query=query, base_params=params,
                                   order_by="statement_id", page_size=batch_size):
            statement_ids = [str(row["statement_id"]) for row in page]
            contexts = fetch_contexts(conn, statement_ids, joins)

            for sid in statement_ids:
                if sid not in contexts:
                    skipped += 1
                    continue
                prompt_text = render_prompt(spec.template, contexts[sid])
                req = _build_request(sid, prompt_text, model_config)
                if splitting and rows_in_file >= rows_per_file:
                    finalize_output(f_out, current_local, current_dest)
                    file_index   += 1
                    rows_in_file  = 0
                    current_dest  = indexed_path(output_str, file_index)
                    current_local, f_out = open_output(current_dest)
                f_out.write(json.dumps(req, ensure_ascii=False) + "\n")
                written      += 1
                rows_in_file += 1

            pbar.update(len(page))
            pbar.set_postfix({"written": written, "skipped": skipped})

    finalize_output(f_out, current_local, current_dest)
    n_files = file_index + 1
    dest_display = (output_str if is_dir
                    else indexed_path(output_str, 0).replace("_0000", "_*") if splitting
                    else current_dest)
    print(f"\nDone. {written} requests in {n_files} file(s) → {dest_display}, {skipped} statements skipped.")


if __name__ == "__main__":
    parser = ArgumentParser(description="Generate per-statement slogan JSONL batch for Nebius.")
    parser.add_argument("-p", "--prompt", required=True, dest="prompt_name",
                        help="Prompt name from generate_slogans/prompts/ (e.g. context-0).")
    parser.add_argument("-m", "--model", required=True, dest="model_name",
                        help="Short model name from models.json (e.g. qwen3-235b).")
    parser.add_argument("-o", "--output", type=str, default=None,
                        help="Output path (local or s3://). Defaults to per-pair S3 input dir.")
    parser.add_argument("-c", "--condition", type=str, nargs="+", metavar=("SQL", "PARAM"),
                        help="SQL WHERE condition on statement (and optionally paper), followed by bind params.")
    parser.add_argument("--overwrite", action="store_true",
                        help="Include statements that already have a slogan for this prompt+model.")
    parser.add_argument("-b", "--batch-size", type=int, default=64, dest="batch_size",
                        help="Statements per DB page (default: 64).")
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--n-shards", type=int, default=1, dest="n_shards")
    parser.add_argument("--sample", type=int, default=-1,
                        help="Randomly sample this many statements (for testing). Uses TABLESAMPLE BERNOULLI.")
    parser.add_argument("--rows-per-file", type=int, default=-1, dest="rows_per_file",
                        help="Split output into files of at most N rows.")

    args = parser.parse_args()

    if args.condition and len(args.condition) >= 2:
        condition, *condition_params = args.condition
    else:
        condition        = args.condition[0] if args.condition else None
        condition_params = []

    output = args.output or _default_input_dir(args.model_name, args.prompt_name)

    print_script_header(
        action="Preparing slogan batch",
        params={
            "prompt":      args.prompt_name,
            "model":       args.model_name,
            "output":      output,
            "condition?":  condition,
            "params?":     condition_params or None,
            "overwrite":   args.overwrite,
            "batch size":  args.batch_size,
            "shard?":      f"{args.shard}/{args.n_shards}" if args.n_shards > 1 else None,
            "sample?":     args.sample if args.sample > 0 else None,
            "rows/file?":  args.rows_per_file if args.rows_per_file > 0 else None,
        },
    )

    prepare_batch(
        output=output,
        prompt_name=args.prompt_name,
        model_name=args.model_name,
        condition=condition,
        condition_params=condition_params,
        overwrite=args.overwrite,
        batch_size=args.batch_size,
        shard=args.shard,
        n_shards=args.n_shards,
        sample=args.sample,
        rows_per_file=args.rows_per_file,
    )
