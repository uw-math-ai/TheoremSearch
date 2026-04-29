"""
Phase 1: Generate per-statement notation JSONL batch for Nebius batch inference.

Each request renders notation.j2 for one statement. custom_id = statement_id
so Phase 2 (connect) can look up all metadata from the DB.

Run:
    python -m pipeline.parse_notations.batch.prepare -m qwen3-235b
    python -m pipeline.parse_notations.batch.prepare -m qwen3-235b -o s3://bucket/notation_batches/input/
    python -m pipeline.parse_notations.batch.prepare -m qwen3-235b -c "paper.kind = 'paper'"
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

_S3_BUCKET   = "dependency-graph-bucket"
_S3_FOLDER   = "notation_batches"
_MODELS_FILE = Path(__file__).parent.parent / "models.json"
_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _default_input_dir() -> str:
    return f"s3://{_S3_BUCKET}/{_S3_FOLDER}/input/"


def _load_model_config(name: str) -> dict:
    with open(_MODELS_FILE) as f:
        models = json.load(f)
    if name not in models:
        raise ValueError(f"Model '{name}' not in models.json. Available: {list(models)}")
    return models[name]


def _jinja_env():
    return Environment(
        loader=FileSystemLoader(_PROMPTS_DIR),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def _build_request(statement: dict, model_config: dict, template) -> dict:
    prompt = template.render(statement=statement)
    return {
        "custom_id": str(statement["statement_id"]),
        "method":    "POST",
        "url":       "/v1/chat/completions",
        "body": {
            "model":      model_config["model"],
            "messages":   [{"role": "user", "content": prompt}],
            "max_tokens": model_config.get("max_tokens", 512),
        },
    }


def prepare_batch(
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

    conn     = get_rds_connection("v2")
    template = _jinja_env().get_template("notation.j2")

    query, params = build_query(
        sample=sample,
        base_query="SELECT paper.paper_id FROM paper",
        where_clauses=[
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

    with tqdm(total=total, dynamic_ncols=True, unit=" papers", desc="Preparing") as pbar:
        for page in paginate_query(conn, base_query=query, base_params=params,
                                   order_by="paper_id", page_size=batch_size):
            paper_ids = [str(p["paper_id"]) for p in page]

            if not overwrite:
                already_done = _papers_already_processed(conn, paper_ids)
                to_process   = [pid for pid in paper_ids if pid not in already_done]
                skipped     += len(paper_ids) - len(to_process)
                paper_ids    = to_process

            if paper_ids:
                stmts_by_paper = _fetch_paper_statements(conn, paper_ids)
                for pid in paper_ids:
                    for stmt in stmts_by_paper.get(pid, []):
                        req = _build_request(stmt, model_config, template)
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
    print(f"\nDone. {written} requests in {n_files} file(s) → {dest_display}, {skipped} papers skipped.")


if __name__ == "__main__":
    parser = ArgumentParser(description="Generate per-statement notation JSONL batch for Nebius.")
    parser.add_argument("-m", "--model", required=True, dest="model_name",
                        help="Short model name from models.json (e.g. qwen3-235b).")
    parser.add_argument("-o", "--output", type=str, default=None,
                        help=f"Output path (local or s3://). Default: {_default_input_dir()}")
    parser.add_argument("-c", "--condition", type=str, nargs="+", metavar=("SQL", "PARAM"),
                        help="SQL WHERE condition on paper, followed by bind params.")
    parser.add_argument("--overwrite", action="store_true",
                        help="Include papers that already have llm deps (default: skip them).")
    parser.add_argument("-b", "--batch-size", type=int, default=64, dest="batch_size",
                        help="Papers per DB page (default: 64).")
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--n-shards", type=int, default=1, dest="n_shards")
    parser.add_argument("--sample", type=int, default=-1,
                        help="Randomly sample this many papers (for testing).")
    parser.add_argument("--rows-per-file", type=int, default=-1, dest="rows_per_file",
                        help="Split output into files of at most N rows.")

    args = parser.parse_args()

    if args.condition and len(args.condition) >= 2:
        condition, *condition_params = args.condition
    else:
        condition        = args.condition[0] if args.condition else None
        condition_params = []

    model_config = _load_model_config(args.model_name)
    output       = args.output or _default_input_dir()

    print_script_header(
        action="Preparing notation batch",
        params={
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
