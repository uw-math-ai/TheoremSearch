"""
Phase 1: Generate an OpenAI-compatible JSONL batch file for concept-extraction inference.

Each request contains a paper's statements (body only) and asks the model to list
what each statement defines and uses. The custom_id is the paper's arxiv_id so
Phase 3 (connect) can re-derive all state from the DB using only that key.

Run:
    python -m pipeline.parse_dependencies.batch.prepare
    python -m pipeline.parse_dependencies.batch.prepare -o s3://bucket/concepts/input/
    python -m pipeline.parse_dependencies.batch.prepare -c "aps.parsed = TRUE"
"""

import json
import tempfile
from argparse import ArgumentParser
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Union

from jinja2 import Environment, FileSystemLoader
from tqdm import tqdm

from rds.utils.connect import get_rds_connection
from rds.utils.query import build_query, get_query_count
from rds.utils.paginate import paginate_query
import boto3

from ...printing import print_script_header


_S3_BUCKET  = "dependency-graph-bucket"
_S3_FOLDER  = "concepts_llm_batches"

_CONCEPT_KINDS = frozenset({
    "definition", "theorem", "proposition", "corollary", "lemma", "notation",
})

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_jinja_env   = Environment(loader=FileSystemLoader(_PROMPTS_DIR), keep_trailing_newline=True)


def _default_output() -> str:
    return f"s3://{_S3_BUCKET}/{_S3_FOLDER}/input/"


def _parse_s3_uri(uri: str):
    without_scheme = uri[len("s3://"):]
    bucket, _, key = without_scheme.partition("/")
    return bucket, key


def _indexed_output(output_str: str, index: int) -> str:
    if output_str.endswith("/"):
        return f"{output_str}{index:03d}.jsonl"
    if output_str.startswith("s3://"):
        base, _, name = output_str.rpartition("/")
        stem, dot, ext = name.rpartition(".")
        return f"{base}/{stem}_{index:04d}.{ext}" if dot else f"{base}/{name}_{index:04d}"
    p = Path(output_str)
    return str(p.parent / f"{p.stem}_{index:04d}{p.suffix}")


def _clear_s3_folder(prefix: str):
    bucket, key = _parse_s3_uri(prefix)
    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    to_delete = []
    for page in paginator.paginate(Bucket=bucket, Prefix=key):
        for obj in page.get("Contents", []):
            to_delete.append({"Key": obj["Key"]})
    if to_delete:
        s3.delete_objects(Bucket=bucket, Delete={"Objects": to_delete})


def _list_s3_files(prefix: str) -> List[str]:
    bucket, key = _parse_s3_uri(prefix)
    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    uris = []
    for page in paginator.paginate(Bucket=bucket, Prefix=key):
        for obj in page.get("Contents", []):
            uris.append(f"s3://{bucket}/{obj['Key']}")
    return sorted(uris)


def _open_output(dest: str):
    if dest.startswith("s3://"):
        tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        tmp.close()
        local = Path(tmp.name)
    else:
        local = Path(dest)
    return local, local.open("w", encoding="utf-8")


def _finalize_output(f_out, local_path: Path, dest: str):
    f_out.close()
    if dest.startswith("s3://"):
        bucket, key = _parse_s3_uri(dest)
        boto3.client("s3").upload_file(str(local_path), bucket, key)
        local_path.unlink()


def _build_concepts_request(
    arxiv_id: str,
    statements: List[Dict],
    model: str,
    system_prompt: str,
    max_tokens: int,
    max_statements: int,
) -> Optional[dict]:
    if not statements:
        return None

    stmts = (
        statements if len(statements) <= max_statements
        else [s for s in statements if s["kind"] in _CONCEPT_KINDS]
    )
    if not stmts:
        return None

    stmt_items = [
        {"id": s["statement_id"], "kind": s["kind"], **({"body": s["body"]} if s.get("body") else {})}
        for s in stmts
    ]

    return {
        "custom_id": arxiv_id,
        "method":    "POST",
        "url":       "/v1/chat/completions",
        "body": {
            "model":      model,
            "messages":   [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": json.dumps(stmt_items, ensure_ascii=False)},
            ],
            "max_tokens": max_tokens,
        },
    }


def prepare_batch(
    output: Union[str, Path],
    model: str,
    max_tokens: int,
    max_statements: int,
    batch_size: int,
    condition: Optional[str],
    condition_params: List[str],
    shard: int,
    n_shards: int,
    sample: int = -1,
    rows_per_file: int = -1,
):
    output_str = str(output)
    is_dir     = output_str.endswith("/")
    splitting  = rows_per_file > 0

    if is_dir and output_str.startswith("s3://"):
        print(f"Clearing {output_str} ...")
        _clear_s3_folder(output_str)

    conn          = get_rds_connection("v2")
    system_prompt = _jinja_env.get_template("intrapaper_llm_system.j2").render()
    needs_aps     = condition and "aps." in condition

    query, params = build_query(
        sample=sample,
        base_query=(
            "SELECT paper.paper_id, paper.external_id"
            " FROM paper"
            + (" LEFT JOIN arxiv_parse_status AS aps ON aps.arxiv_id = paper.external_id" if needs_aps else "")
        ),
        where_clauses=[
            {
                "if": True,
                "condition": "paper.kind = 'paper'",
            },
            {
                "if": True,
                "condition": "(SELECT COUNT(*) FROM statement s WHERE s.paper_id = paper.paper_id) > 1",
            },
            {
                "if": condition,
                "condition": condition,
                "params": condition_params,
            },
            {
                "if": n_shards > 1,
                "condition": "hashtext(paper.paper_id::text) %% %s = %s",
                "params": [n_shards, shard],
            },
        ],
    )

    count       = get_query_count(conn, query, params)
    skipped     = written = total_chars = 0
    file_index  = 0
    rows_in_file = 0
    current_dest  = _indexed_output(output_str, file_index) if (splitting or is_dir) else output_str
    current_local, f_out = _open_output(current_dest)

    with tqdm(total=count, dynamic_ncols=True, unit=" papers", desc="Preparing") as pbar:
        for papers in paginate_query(
            conn,
            base_query=query,
            base_params=params,
            order_by="paper_id",
            page_size=batch_size,
        ):
            paper_ids = [p["paper_id"]    for p in papers]
            arxiv_ids = [p["external_id"] for p in papers]  # noqa: F841

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT s.statement_id, s.paper_id, s.kind, s.body, im.ref
                    FROM statement s
                    INNER JOIN informal_metadata im ON im.statement_id = s.statement_id
                    WHERE s.paper_id = ANY(%s::uuid[])
                    ORDER BY s.paper_id, im.ordinal
                    """,
                    (paper_ids,),
                )
                stmts_by_paper: Dict[str, list] = defaultdict(list)
                for row in cur.fetchall():
                    stmt = dict(zip(["statement_id", "paper_id", "kind", "body", "ref"], row))
                    stmts_by_paper[stmt["paper_id"]].append(stmt)

            for paper in papers:
                arxiv_id = paper["external_id"]
                stmts    = stmts_by_paper.get(paper["paper_id"], [])
                req      = _build_concepts_request(
                    arxiv_id, stmts, model, system_prompt, max_tokens, max_statements
                )

                if req is None:
                    skipped += 1
                else:
                    if splitting and rows_in_file >= rows_per_file:
                        _finalize_output(f_out, current_local, current_dest)
                        file_index  += 1
                        rows_in_file = 0
                        current_dest  = _indexed_output(output_str, file_index)
                        current_local, f_out = _open_output(current_dest)
                    f_out.write(json.dumps(req, ensure_ascii=False) + "\n")
                    total_chars  += sum(len(m["content"]) for m in req["body"]["messages"])
                    written      += 1
                    rows_in_file += 1

            pbar.update(len(papers))
            pbar.set_postfix({"written": written, "skipped": skipped})

    _finalize_output(f_out, current_local, current_dest)
    n_files = file_index + 1
    if is_dir:
        dest_display = output_str
    elif splitting:
        dest_display = _indexed_output(output_str, 0).replace("_0000", "_*")
    else:
        dest_display = current_dest
    est_tokens = total_chars // 4
    print(
        f"\nDone. {written} requests written to {n_files} file(s) ({dest_display}), {skipped} skipped."
        f"\n  Estimated input tokens: ~{est_tokens:,} (~{total_chars:,} chars ÷ 4)"
    )


if __name__ == "__main__":
    arg_parser = ArgumentParser(
        description="Generate a JSONL batch file for concept-extraction inference."
    )

    arg_parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help=f"Output path: local file or s3://bucket/key. Default: {_default_output()}",
    )
    arg_parser.add_argument(
        "--model",
        type=str,
        default="Qwen/Qwen3-235B-A22B-Instruct-2507",
        help="Model ID to embed in each batch request (default: Qwen/Qwen3-235B-A22B-Instruct-2507).",
    )
    arg_parser.add_argument(
        "--max-tokens",
        type=int,
        default=16384,
        dest="max_tokens",
        help="Maximum output tokens per request (default: 16384).",
    )
    arg_parser.add_argument(
        "--max-statements",
        type=int,
        default=100,
        dest="max_statements",
        help=(
            "When a paper exceeds this many statements, only the most important kinds "
            "(definition, theorem, proposition, corollary, lemma, notation) are sent "
            "(default: 100)."
        ),
    )
    arg_parser.add_argument(
        "-b", "--batch-size",
        type=int,
        default=256,
        dest="batch_size",
        help="Papers fetched from DB per iteration (default: 256).",
    )
    arg_parser.add_argument(
        "-c", "--condition",
        type=str,
        nargs="+",
        metavar=("SQL", "PARAM"),
        help="SQL WHERE condition to filter papers, followed by any bind parameters.",
    )
    arg_parser.add_argument(
        "--shard",
        type=int,
        default=0,
    )
    arg_parser.add_argument(
        "--n-shards",
        type=int,
        default=1,
        dest="n_shards",
    )
    arg_parser.add_argument(
        "--sample",
        type=int,
        default=-1,
        help="Randomly sample this many papers (for testing). Uses TABLESAMPLE BERNOULLI.",
    )
    arg_parser.add_argument(
        "--rows-per-file",
        type=int,
        default=-1,
        dest="rows_per_file",
        help="Split output into files of at most this many rows (_0000, _0001, … suffixes).",
    )

    args = arg_parser.parse_args()

    if args.condition and len(args.condition) >= 2:
        condition, *condition_params = args.condition
    else:
        condition        = args.condition[0] if args.condition else None
        condition_params = []

    output = args.output if args.output is not None else _default_output()

    print_script_header(
        action="Preparing concepts batch",
        params={
            "output":           output,
            "model":            args.model,
            "max tokens":       args.max_tokens,
            "max statements":   args.max_statements,
            "batch size":       args.batch_size,
            "condition?":       condition,
            "params?":          condition_params or None,
            "shard?":           f"{args.shard}/{args.n_shards}" if args.n_shards > 1 else None,
            "sample?":          args.sample if args.sample > 0 else None,
            "rows/file?":       args.rows_per_file if args.rows_per_file > 0 else None,
        },
    )

    prepare_batch(
        output=output,
        model=args.model,
        max_tokens=args.max_tokens,
        max_statements=args.max_statements,
        batch_size=args.batch_size,
        condition=condition,
        condition_params=condition_params,
        shard=args.shard,
        n_shards=args.n_shards,
        sample=args.sample,
        rows_per_file=args.rows_per_file,
    )
