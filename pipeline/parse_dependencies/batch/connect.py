"""
Phase 3: Write LLM batch results into the database.

Run:
    python -m pipeline.parse_dependencies.batch.connect --inter
    python -m pipeline.parse_dependencies.batch.connect --intra
    python -m pipeline.parse_dependencies.batch.connect --inter -i s3://bucket/custom_results.jsonl

Input file format: OpenAI Batch API output JSONL. Each line:
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

from .prepare import _parse_s3_uri, _list_s3_files, _S3_BUCKET, _S3_FOLDERS
from ...printing import print_script_header
from ..interpaper import connect_inter_llm_results
from ..intrapaper import connect_intra_llm_results
from rds.utils.connect import get_rds_connection


def _default_output_dir(dep_type: str) -> str:
    return f"s3://{_S3_BUCKET}/{_S3_FOLDERS[dep_type]}/output/"


def _iter_results(paths: List[str]) -> Iterator[Tuple[str, str]]:
    """Yield (arxiv_id, llm_text) from one or more batch results JSONL paths.

    Skips failed/malformed entries with warnings. Raises if a file is
    missing or if no valid results are found across all paths.
    """
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
                    if status != 200:
                        print(
                            f"  Warning: {arxiv_id} returned status {status}, skipping.",
                            file=sys.stderr,
                        )
                        skipped += 1
                        continue

                    try:
                        text = response["body"]["choices"][0]["message"]["content"]
                    except (KeyError, IndexError, TypeError):
                        print(
                            f"  Warning: {arxiv_id} has malformed response body, skipping.",
                            file=sys.stderr,
                        )
                        skipped += 1
                        continue

                    yield arxiv_id, text
                    yielded += 1

        finally:
            if is_s3:
                local_path.unlink(missing_ok=True)

    if yielded == 0:
        detail = f"{skipped} entries were skipped due to errors." if skipped else "Files may be empty."
        raise ValueError(f"No valid results found. {detail}")

    if skipped:
        print(f"  {skipped} failed/malformed entries skipped.", file=sys.stderr)


def connect_batch(
    dep_type: str,
    input_paths: List[str],
    similarity_threshold: float,
    batch_size: int,
):
    conn    = get_rds_connection("v2")
    results = _iter_results(input_paths)

    if dep_type == "inter":
        stats = connect_inter_llm_results(
            conn=conn,
            results=results,
            similarity_threshold=similarity_threshold,
            batch_size=batch_size,
        )
    else:
        stats = connect_intra_llm_results(
            conn=conn,
            results=results,
            batch_size=batch_size,
        )

    print(
        f"\nDone. {stats['written']} dep rows written, "
        f"{stats['failed']} papers failed to parse."
    )


if __name__ == "__main__":
    arg_parser = ArgumentParser(
        description="Write LLM batch results into the database."
    )
    arg_parser.add_argument(
        "--inter",
        action="store_true",
        help="Connect inter-paper results.",
    )
    arg_parser.add_argument(
        "--intra",
        action="store_true",
        help="Connect intra-paper results.",
    )
    arg_parser.add_argument(
        "-i", "--input",
        type=str,
        nargs="+",
        default=None,
        dest="input_paths",
        help="Results JSONL file(s) or S3 directory (default: s3 output/ dir for the type).",
    )
    arg_parser.add_argument(
        "-s", "--similarity-threshold",
        type=float,
        default=0.8,
        dest="similarity_threshold",
        help="pg_trgm title-match threshold for inter-paper resolution (default: 0.8). Ignored for intra.",
    )
    arg_parser.add_argument(
        "-b", "--batch-size",
        type=int,
        default=256,
        dest="batch_size",
        help="Papers flushed to DB per transaction (default: 256).",
    )

    args = arg_parser.parse_args()

    dep_types = [t for t, flag in [("inter", args.inter), ("intra", args.intra)] if flag] or ["inter", "intra"]

    if args.input_paths and len(dep_types) > 1:
        arg_parser.error("-i/--input cannot be used when connecting both types.")

    for dep_type in dep_types:
        # Resolve input paths
        if args.input_paths:
            input_paths = args.input_paths
        else:
            output_dir = _default_output_dir(dep_type)
            input_paths = _list_s3_files(output_dir)
            if not input_paths:
                print(f"No result files found in {output_dir}, skipping {dep_type}.")
                continue

        print_script_header(
            action=f"Connecting {dep_type}paper LLM batch results",
            params={
                "input":              args.input_paths or _default_output_dir(dep_type),
                "batch size":         args.batch_size,
                "*similarity-thresh": args.similarity_threshold if dep_type == "inter" else None,
            },
        )

        connect_batch(
            dep_type=dep_type,
            input_paths=input_paths,
            similarity_threshold=args.similarity_threshold,
            batch_size=args.batch_size,
        )
