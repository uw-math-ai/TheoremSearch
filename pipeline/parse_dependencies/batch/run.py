"""
Phase 2: Submit a prepared JSONL batch to the LLM Batch API and download results.

Run:
    python -m pipeline.parse_dependencies.batch.run --inter
    python -m pipeline.parse_dependencies.batch.run --intra
    python -m pipeline.parse_dependencies.batch.run --inter -i s3://bucket/custom.jsonl -o s3://bucket/out/

Resume a previously-submitted batch:
    python -m pipeline.parse_dependencies.batch.run --inter --resume-id batch_xxx
"""

import json
import os
import tempfile
import time
from argparse import ArgumentParser
from pathlib import Path
from typing import List, Optional

import boto3
from openai import OpenAI
from tqdm import tqdm

from .prepare import _parse_s3_uri, _clear_s3_folder, _list_s3_files, _S3_BUCKET, _S3_FOLDERS
from ...printing import print_script_header

_DEFAULT_BASE_URL  = "https://api.studio.nebius.ai/v1/"
_DEFAULT_KEY_ENV   = "NEBIUS_API_KEY"
_POLL_INTERVAL     = 30  # seconds
_TERMINAL_STATUSES = {"completed", "failed", "expired", "cancelled"}


def _default_input_dir(dep_type: str) -> str:
    return f"s3://{_S3_BUCKET}/{_S3_FOLDERS[dep_type]}/input/"


def _default_output_dir(dep_type: str) -> str:
    return f"s3://{_S3_BUCKET}/{_S3_FOLDERS[dep_type]}/output/"


def _make_client(api_key_env: str, base_url: str) -> OpenAI:
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise EnvironmentError(
            f"Environment variable {api_key_env!r} is not set.\n"
            f"Run: export {api_key_env}=<your-api-key>"
        )
    return OpenAI(api_key=api_key, base_url=base_url)


def _state_path(dep_type: str) -> Path:
    return Path(f".{dep_type}_batch.run_state.json")


def _load_state(path: Path) -> Optional[dict]:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return None


def _save_state(path: Path, state: dict):
    path.write_text(json.dumps(state, indent=2))


def _download_s3_to_tmp(uri: str) -> Path:
    bucket, key = _parse_s3_uri(uri)
    tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
    tmp.close()
    try:
        boto3.client("s3").download_file(bucket, key, tmp.name)
    except Exception as e:
        Path(tmp.name).unlink(missing_ok=True)
        raise FileNotFoundError(
            f"Could not download {uri}: {e}\n"
            "Check that the file exists and your AWS credentials are configured."
        )
    return Path(tmp.name)


def _concat_s3_files(uris: List[str]) -> Path:
    """Download and concatenate multiple S3 JSONL files into one temp file."""
    tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
    tmp.close()
    local = Path(tmp.name)
    with local.open("wb") as out:
        for uri in uris:
            part = _download_s3_to_tmp(uri)
            try:
                out.write(part.read_bytes())
            finally:
                part.unlink(missing_ok=True)
    return local


def _submit(client: OpenAI, local_input: Path) -> str:
    """Upload the batch file and create a batch job. Returns the batch ID."""
    print(f"Uploading {local_input} ({local_input.stat().st_size / 1024:.1f} KB) ...")
    with local_input.open("rb") as f:
        uploaded = client.files.create(file=f, purpose="batch")
    print(f"  File ID: {uploaded.id}")

    batch = client.batches.create(
        input_file_id=uploaded.id,
        endpoint="/v1/chat/completions",
        completion_window="24h",
    )
    print(f"  Batch ID: {batch.id}  (status: {batch.status})")
    return batch.id


def _poll(client: OpenAI, batch_id: str, state_path: Path):
    """Poll until the batch reaches a terminal status. Returns the batch object."""
    print(f"Polling batch {batch_id} every {_POLL_INTERVAL}s ...")
    while True:
        batch = client.batches.retrieve(batch_id)
        _save_state(state_path, {"batch_id": batch_id, "status": batch.status})

        c = batch.request_counts
        tqdm.write(f"  [{batch.status}]  {c.completed}/{c.total} done, {c.failed} failed")

        if batch.status in _TERMINAL_STATUSES:
            return batch
        time.sleep(_POLL_INTERVAL)


def _write_output(content: str, output: str):
    if output.startswith("s3://"):
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8")
        tmp.write(content)
        tmp.close()
        local = Path(tmp.name)
        bucket, key = _parse_s3_uri(output)
        boto3.client("s3").upload_file(str(local), bucket, key)
        local.unlink()
        print(f"Results uploaded to {output}")
    else:
        Path(output).write_text(content, encoding="utf-8")
        print(f"Results written to {output}")


def _download_results(client: OpenAI, batch, output: str):
    if batch.status != "completed":
        errors = getattr(batch, "errors", None)
        raise RuntimeError(
            f"Batch {batch.id} ended with status '{batch.status}'.\n"
            + (f"Errors: {errors}" if errors else "Check the provider dashboard for details.")
        )

    if not batch.output_file_id:
        raise RuntimeError(
            f"Batch {batch.id} completed but produced no output file.\n"
            f"All {batch.request_counts.total} request(s) may have failed — "
            "check the provider dashboard for the error file."
        )

    print(f"Downloading results (file: {batch.output_file_id}) ...")
    content = client.files.content(batch.output_file_id).text
    _write_output(content, output)
    print(f"  {content.count(chr(10))} result lines total.")

    if batch.request_counts.failed > 0:
        print(
            f"  Warning: {batch.request_counts.failed} request(s) failed and will be skipped by connect.\n"
            f"  Error file ID: {batch.error_file_id}"
        )


def run_batch(
    dep_type: str,
    input_path: Optional[str],
    output: Optional[str],
    api_key_env: str,
    base_url: str,
    resume_id: Optional[str],
):
    client     = _make_client(api_key_env, base_url)
    state_path = _state_path(dep_type)

    # Resolve output to a single file (directory → 000.jsonl inside it)
    if output is None:
        output_dir = _default_output_dir(dep_type)
        output = f"{output_dir}000.jsonl"
    elif output.endswith("/"):
        output = f"{output}000.jsonl"

    batch_id = resume_id

    if batch_id is None:
        state = _load_state(state_path)
        if state:
            existing_id     = state.get("batch_id")
            existing_status = state.get("status", "")
            if existing_id and existing_status not in _TERMINAL_STATUSES:
                print(
                    f"Found in-progress batch {existing_id} (status: {existing_status}). Resuming.\n"
                    "Pass --resume-id to override."
                )
                batch_id = existing_id

    cleanup = False
    if batch_id is None:
        # Resolve input: directory → list all files and concatenate
        if input_path is None:
            input_path = _default_input_dir(dep_type)

        if input_path.endswith("/") and input_path.startswith("s3://"):
            uris = _list_s3_files(input_path)
            if not uris:
                raise FileNotFoundError(
                    f"No files found in {input_path}\n"
                    "Run 'python -m pipeline.parse_dependencies.batch.prepare' first."
                )
            print(f"Found {len(uris)} input file(s) in {input_path}, concatenating ...")
            local_input = _concat_s3_files(uris)
            cleanup = True
        elif input_path.startswith("s3://"):
            print(f"Downloading input from {input_path} ...")
            local_input = _download_s3_to_tmp(input_path)
            cleanup = True
        else:
            local_input = Path(input_path)
            if not local_input.exists():
                raise FileNotFoundError(
                    f"Input file not found: {input_path}\n"
                    "Run 'python -m pipeline.parse_dependencies.batch.prepare' first."
                )
            if local_input.stat().st_size == 0:
                raise ValueError(
                    f"Input file is empty: {input_path}\n"
                    "The prepare step may have found no eligible papers."
                )

        # Clear output dir before writing
        output_prefix = output.rsplit("/", 1)[0] + "/"
        if output_prefix.startswith("s3://"):
            print(f"Clearing {output_prefix} ...")
            _clear_s3_folder(output_prefix)

        try:
            batch_id = _submit(client, local_input)
            _save_state(state_path, {"batch_id": batch_id, "status": "in_progress"})
        finally:
            if cleanup:
                local_input.unlink(missing_ok=True)

    batch = _poll(client, batch_id, state_path)
    _download_results(client, batch, output)
    state_path.unlink(missing_ok=True)


if __name__ == "__main__":
    arg_parser = ArgumentParser(
        description="Submit a JSONL batch to the LLM Batch API and download results."
    )
    arg_parser.add_argument(
        "--inter",
        action="store_true",
        help="Run inter-paper batch.",
    )
    arg_parser.add_argument(
        "--intra",
        action="store_true",
        help="Run intra-paper batch.",
    )
    arg_parser.add_argument(
        "-i", "--input",
        type=str,
        default=None,
        dest="input_path",
        help="Input JSONL or S3 directory (default: s3 input/ dir for the type).",
    )
    arg_parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Output JSONL file or S3 directory (default: s3 output/000.jsonl for the type).",
    )
    arg_parser.add_argument(
        "--resume-id",
        type=str,
        default=None,
        dest="resume_id",
        help="Skip submission and poll/download an already-submitted batch ID.",
    )
    arg_parser.add_argument(
        "--api-key-env",
        type=str,
        default=_DEFAULT_KEY_ENV,
        dest="api_key_env",
        help=f"Name of the env var holding the API key (default: {_DEFAULT_KEY_ENV}).",
    )
    arg_parser.add_argument(
        "--base-url",
        type=str,
        default=_DEFAULT_BASE_URL,
        dest="base_url",
        help=f"API base URL (default: {_DEFAULT_BASE_URL}).",
    )

    args = arg_parser.parse_args()

    dep_types = [t for t, flag in [("inter", args.inter), ("intra", args.intra)] if flag] or ["inter", "intra"]

    if (args.input_path or args.output or args.resume_id) and len(dep_types) > 1:
        arg_parser.error("-i/-o/--resume-id cannot be used when running both types.")

    for dep_type in dep_types:
        print_script_header(
            action=f"Running {dep_type}paper LLM batch",
            params={
                "input?":      args.input_path,
                "output?":     args.output,
                "resume-id?":  args.resume_id,
                "api-key-env": args.api_key_env,
                "base-url":    args.base_url,
            },
        )

        run_batch(
            dep_type=dep_type,
            input_path=args.input_path,
            output=args.output,
            api_key_env=args.api_key_env,
            base_url=args.base_url,
            resume_id=args.resume_id,
        )
