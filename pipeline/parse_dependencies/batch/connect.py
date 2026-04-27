"""
Phase 3: Write concept-extraction batch results into the database.

Run:
    python -m pipeline.parse_dependencies.batch.connect
    python -m pipeline.parse_dependencies.batch.connect -i s3://bucket/concepts/output/results.jsonl
    python -m pipeline.parse_dependencies.batch.connect -i results.jsonl

Input file format: Nebius Batch API output JSONL. Each line:
    {"custom_id": "<arxiv_id>", "response": {"status_code": 200, "body": {"choices": [...]}}, "error": null}

Errors from prior steps raise immediately with a clear message. Per-paper parse
failures are logged as warnings and skipped without aborting the run.
"""

import json
import sys
import tempfile
from argparse import ArgumentParser
from pathlib import Path
from typing import Iterator, List, Tuple

import boto3

from .prepare import _parse_s3_uri, _list_s3_files, _S3_BUCKET, _S3_FOLDER
from ...printing import print_script_header
from ..intrapaper import connect_intra_llm_results
from rds.utils.connect import get_rds_connection


def _default_output_dir() -> str:
    return f"s3://{_S3_BUCKET}/{_S3_FOLDER}/output/"


def _iter_results(paths: List[str]) -> Iterator[Tuple[str, str]]:
    """Yield (arxiv_id, llm_text) from one or more batch result JSONL paths."""
    skipped = yielded = 0

    for path in paths:
        is_s3 = path.startswith("s3://")
        if is_s3:
            bucket, key = _parse_s3_uri(path)
            tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
            tmp.close()
            try:
                boto3.client("s3").download_file(bucket, key, tmp.name)
            except Exception as e:
                Path(tmp.name).unlink(missing_ok=True)
                raise FileNotFoundError(
                    f"Could not download results from {path}: {e}\n"
                    "Run 'python -m pipeline.parse_dependencies.batch.run' first."
                )
            local_path = Path(tmp.name)
        else:
            local_path = Path(path)
            if not local_path.exists():
                raise FileNotFoundError(
                    f"Results file not found: {path}\n"
                    "Run 'python -m pipeline.parse_dependencies.batch.run' first."
                )
            if local_path.stat().st_size == 0:
                raise ValueError(
                    f"Results file is empty: {path}\n"
                    "The batch may have produced no output — check run logs."
                )

        try:
            with local_path.open(encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        print(f"  Warning: line {lineno} in {path} is not valid JSON, skipping.", file=sys.stderr)
                        skipped += 1
                        continue

                    arxiv_id = obj.get("custom_id", "").strip()
                    if not arxiv_id:
                        print(f"  Warning: line {lineno} in {path} has no custom_id, skipping.", file=sys.stderr)
                        skipped += 1
                        continue

                    error = obj.get("error")
                    if error:
                        msg = error.get("message") or error if isinstance(error, str) else error
                        print(f"  Warning: {arxiv_id} — API error: {msg}", file=sys.stderr)
                        skipped += 1
                        continue

                    response = obj.get("response") or {}
                    status   = response.get("status_code")
                    # OpenAI batch format wraps in {"status_code": 200, "body": {...}};
                    # Nebius Token Factory returns the completion object directly.
                    if status is not None:
                        if status != 200:
                            print(f"  Warning: {arxiv_id} returned status {status}, skipping.", file=sys.stderr)
                            skipped += 1
                            continue
                        body = response.get("body") or {}
                    else:
                        body = response

                    try:
                        text = body["choices"][0]["message"]["content"]
                    except (KeyError, IndexError, TypeError):
                        print(f"  Warning: {arxiv_id} has malformed response body, skipping.", file=sys.stderr)
                        skipped += 1
                        continue

                    yield arxiv_id, text, body.get("usage") or {}
                    yielded += 1

        finally:
            if is_s3:
                local_path.unlink(missing_ok=True)

    if yielded == 0:
        detail = f"{skipped} entries were skipped due to errors." if skipped else "Files may be empty."
        raise ValueError(f"No valid results found. {detail}")

    if skipped:
        print(f"  {skipped} failed/malformed entries skipped.", file=sys.stderr)


if __name__ == "__main__":
    arg_parser = ArgumentParser(
        description="Write concept-extraction batch results into the database."
    )
    arg_parser.add_argument(
        "-i", "--input",
        type=str,
        nargs="+",
        default=None,
        dest="input_paths",
        help=f"Results JSONL file(s) or S3 directory (default: {_default_output_dir()}).",
    )
    arg_parser.add_argument(
        "-b", "--batch-size",
        type=int,
        default=256,
        dest="batch_size",
        help="Papers flushed to DB per transaction (default: 256).",
    )


    args = arg_parser.parse_args()

    if args.input_paths:
        input_paths = args.input_paths
    else:
        output_dir  = _default_output_dir()
        input_paths = _list_s3_files(output_dir)
        if not input_paths:
            print(f"No result files found in {output_dir}.")
            sys.exit(1)

    print_script_header(
        action="Connecting concept-extraction batch results",
        params={
            "input":      args.input_paths or _default_output_dir(),
            "batch size": args.batch_size,
        },
    )

    conn = get_rds_connection("v2")

    token_totals = {"input": 0, "output": 0}

    def _results_with_tokens():
        for arxiv_id, text, usage in _iter_results(input_paths):
            token_totals["input"]  += usage.get("prompt_tokens", 0)
            token_totals["output"] += usage.get("completion_tokens", 0)
            yield arxiv_id, text

    stats = connect_intra_llm_results(conn=conn, results=_results_with_tokens(), batch_size=args.batch_size)

    print(
        f"\nDone. {stats['written']} dep rows written, "
        f"{stats['failed']} papers failed to parse."
        f"\n  Input tokens:  {token_totals['input']:,}"
        f"\n  Output tokens: {token_totals['output']:,}"
    )
