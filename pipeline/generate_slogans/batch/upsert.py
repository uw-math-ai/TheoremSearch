"""
Phase 3: Read Nebius batch results and upsert slogan rows to the database.

Each result line has custom_id = statement_id. The prompt name and model name
must be provided so results can be attributed correctly and prompt/model records
registered before upserting.

Run:
    python -m pipeline.generate_slogans.batch.upsert -p context-0 -m qwen3-235b
    python -m pipeline.generate_slogans.batch.upsert -p context-0 -m qwen3-235b -i results.jsonl
    python -m pipeline.generate_slogans.batch.upsert -p context-0 -m qwen3-235b -i s3://bucket/slogan_batches/output/
"""

import sys
from argparse import ArgumentParser
from datetime import datetime, timezone
from typing import List

from rds.utils.connect import get_rds_connection
from rds.utils.upsert import upsert_rows
from s3.utils.io import list_files
from s3.utils.batch import iter_batch_results
from ...printing import print_script_header
from ..prompt_utils import load_prompt, load_model_config, register_prompt, register_model, parse_slogan_text
from .prepare import _default_output_dir


def upsert_batch_results(
    conn,
    paths: List[str],
    prompt_name: str,
    model_name: str,
    overwrite: bool = False,
) -> dict:
    spec         = load_prompt(prompt_name)
    model_config = load_model_config(model_name)

    register_prompt(conn, spec)
    register_model(conn, model_name, model_config)

    rows     = []
    total_in = total_out = 0

    for statement_id, text, usage in iter_batch_results(paths):
        slogan, insufficient = parse_slogan_text(text)
        rows.append({
            "statement_id":         statement_id,
            "prompt_name":          spec.name,
            "model_name":           model_name,
            "slogan":               slogan,
            "insufficient_context": insufficient,
            "in_tokens":            usage.get("prompt_tokens"),
            "out_tokens":           usage.get("completion_tokens"),
            "created_at":           datetime.now(timezone.utc),
        })
        total_in  += usage.get("prompt_tokens",     0)
        total_out += usage.get("completion_tokens", 0)

    on_conflict = {"with": ["statement_id", "prompt_name", "model_name"]}
    if overwrite:
        # created_at intentionally excluded: preserves original creation time
        on_conflict["replace"] = ["slogan", "insufficient_context", "in_tokens", "out_tokens"]
    # else: DO NOTHING — leave existing (statement_id, prompt_name, model_name) rows untouched.

    if rows:
        upsert_rows(conn, table="slogan", rows=rows, on_conflict=on_conflict)
        conn.commit()

    return {"submitted": len(rows), "total_in": total_in, "total_out": total_out}


if __name__ == "__main__":
    parser = ArgumentParser(description="Upsert slogan batch results to the database.")
    parser.add_argument("-p", "--prompt", required=True, dest="prompt_name",
                        help="Prompt name used when preparing the batch (e.g. context-0).")
    parser.add_argument("-m", "--model", required=True, dest="model_name",
                        help="Model name used when preparing the batch (e.g. qwen3-235b).")
    parser.add_argument("-i", "--input", type=str, nargs="+", default=None, dest="input_paths",
                        help="Results JSONL file(s) or S3 dir. Defaults to the per-pair S3 output dir.")
    parser.add_argument("-o", "--overwrite", action="store_true",
                        help="Replace existing slogan rows on conflict. Without this flag, "
                             "rows whose (statement_id, prompt_name, model_name) already exists "
                             "are skipped.")

    args = parser.parse_args()

    default_output = _default_output_dir(args.model_name, args.prompt_name)

    if args.input_paths:
        input_paths = args.input_paths
    else:
        input_paths = list_files(default_output)
        if not input_paths:
            print(f"No result files found in {default_output}.")
            sys.exit(1)

    print_script_header(
        action="Upserting slogan batch results",
        params={
            "prompt":    args.prompt_name,
            "model":     args.model_name,
            "input":     args.input_paths or default_output,
            "overwrite": args.overwrite,
        },
    )

    conn  = get_rds_connection("v2")
    stats = upsert_batch_results(
        conn, input_paths, args.prompt_name, args.model_name,
        overwrite=args.overwrite,
    )

    verb = "upserted" if args.overwrite else "submitted (existing rows skipped)"
    print(
        f"\nDone. {stats['submitted']} slogan rows {verb}."
        f"\n  Input tokens:  {stats['total_in']:,}"
        f"\n  Output tokens: {stats['total_out']:,}"
    )
