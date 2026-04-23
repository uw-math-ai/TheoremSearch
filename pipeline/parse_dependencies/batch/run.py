"""
Phase 2: Submit a prepared JSONL batch to the Nebius Token Factory Batch API.

Run:
    python -m pipeline.parse_dependencies.batch.run
    python -m pipeline.parse_dependencies.batch.run -i s3://bucket/concepts/input/ -o s3://bucket/out/

Check progress / download results:
    python -m pipeline.parse_dependencies.batch.poll [--download]
"""

import json
import os
import tempfile
from argparse import ArgumentParser
from pathlib import Path
from typing import Optional

import boto3
from openai import OpenAI

from .prepare import _parse_s3_uri, _clear_s3_folder, _list_s3_files, _S3_BUCKET, _S3_FOLDER
from ...printing import print_script_header

_DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
_DEFAULT_KEY_ENV  = "NEBIUS_API_KEY"


def _default_input_dir() -> str:
    return f"s3://{_S3_BUCKET}/{_S3_FOLDER}/input/"


def _default_output_dir() -> str:
    return f"s3://{_S3_BUCKET}/{_S3_FOLDER}/output/"


def _make_client(api_key_env: str, base_url: str) -> OpenAI:
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise EnvironmentError(
            f"Environment variable {api_key_env!r} is not set.\n"
            f"Run: export {api_key_env}=<your-api-key>"
        )
    return OpenAI(api_key=api_key, base_url=base_url)


def _state_path() -> Path:
    return Path(".concepts_batch.run_state.json")


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


def _submit(client: OpenAI, local_input: Path) -> str:
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


def run_batch(
    input_path: Optional[str],
    output: Optional[str],
    api_key_env: str,
    base_url: str,
):
    state_path = _state_path()

    if output is None:
        out_dir = _default_output_dir()
    elif output.endswith("/"):
        out_dir = output
    else:
        out_dir = output.rsplit("/", 1)[0] + "/"

    if out_dir.startswith("s3://"):
        print(f"Clearing {out_dir} ...")
        _clear_s3_folder(out_dir)

    if input_path is None:
        input_path = _default_input_dir()

    if input_path.startswith("s3://") and input_path.endswith("/"):
        input_uris = _list_s3_files(input_path)
        if not input_uris:
            raise FileNotFoundError(
                f"No files found in {input_path}\n"
                "Run 'python -m pipeline.parse_dependencies.batch.prepare' first."
            )
    else:
        if not input_path.startswith("s3://") and not Path(input_path).exists():
            raise FileNotFoundError(
                f"Input file not found: {input_path}\n"
                "Run 'python -m pipeline.parse_dependencies.batch.prepare' first."
            )
        input_uris = [input_path]

    if len(input_uris) > 1:
        print(f"Found {len(input_uris)} input file(s); submitting {len(input_uris)} batches.")

    client  = _make_client(api_key_env, base_url)
    batches = []
    for i, uri in enumerate(input_uris):
        out_file = f"{out_dir}{i:03d}.jsonl"
        is_s3 = uri.startswith("s3://")
        if is_s3:
            print(f"[{i+1}/{len(input_uris)}] Downloading {uri} ...")
            local_input = _download_s3_to_tmp(uri)
        else:
            local_input = Path(uri)
            if local_input.stat().st_size == 0:
                raise ValueError(
                    f"Input file is empty: {uri}\n"
                    "The prepare step may have found no eligible papers."
                )
        try:
            print(f"[{i+1}/{len(input_uris)}] Submitting batch ...")
            batch_id = _submit(client, local_input)
        finally:
            if is_s3:
                local_input.unlink(missing_ok=True)
        batches.append({"batch_id": batch_id, "status": "in_progress", "output_file": out_file})
        _save_state(state_path, {"batches": batches})

    print(f"\nSubmitted {len(batches)} batch(es). Run poll.py to check progress and download results.")


if __name__ == "__main__":
    arg_parser = ArgumentParser(
        description="Submit a concept-extraction JSONL batch to the Nebius Token Factory Batch API."
    )
    arg_parser.add_argument(
        "-i", "--input",
        type=str,
        default=None,
        dest="input_path",
        help=f"Input JSONL or S3 directory (default: {_default_input_dir()}).",
    )
    arg_parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help=f"Output S3 prefix or local directory (default: {_default_output_dir()}).",
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

    print_script_header(
        action="Running concepts LLM batch",
        params={
            "input?":      args.input_path,
            "output?":     args.output,
            "api-key-env": args.api_key_env,
            "base-url":    args.base_url,
        },
    )

    run_batch(
        input_path=args.input_path,
        output=args.output,
        api_key_env=args.api_key_env,
        base_url=args.base_url,
    )
