"""
Phase 2: Submit a prepared JSONL batch to the Nebius Token Factory Batch API.

Run:
    python -m pipeline.parse_notations.batch.run
    python -m pipeline.parse_notations.batch.run -i s3://bucket/notation_batches/input/ -o s3://bucket/notation_batches/output/

Check progress / download results:
    python -m pipeline.parse_notations.batch.poll [--download]
"""

from argparse import ArgumentParser
from pathlib import Path

from pipeline.nebius_batch import make_client, run_batch, _DEFAULT_BASE_URL, _DEFAULT_KEY_ENV
from .prepare import _S3_BUCKET, _S3_FOLDER
from ...printing import print_script_header


def _state_path() -> Path:
    return Path(".notation_batch.run_state.json")


def _default_input_dir() -> str:
    return f"s3://{_S3_BUCKET}/{_S3_FOLDER}/input/"


def _default_output_dir() -> str:
    return f"s3://{_S3_BUCKET}/{_S3_FOLDER}/output/"


if __name__ == "__main__":
    parser = ArgumentParser(
        description="Submit a notation JSONL batch to the Nebius Token Factory Batch API."
    )
    parser.add_argument("-i", "--input", type=str, default=None, dest="input_path",
                        help=f"Input JSONL or S3 directory (default: {_default_input_dir()}).")
    parser.add_argument("-o", "--output", type=str, default=None,
                        help=f"Output S3 prefix or local directory (default: {_default_output_dir()}).")
    parser.add_argument("--api-key-env", type=str, default=_DEFAULT_KEY_ENV, dest="api_key_env",
                        help=f"Env var holding the API key (default: {_DEFAULT_KEY_ENV}).")
    parser.add_argument("--base-url", type=str, default=_DEFAULT_BASE_URL, dest="base_url",
                        help=f"API base URL (default: {_DEFAULT_BASE_URL}).")

    args = parser.parse_args()

    input_path = args.input_path or _default_input_dir()
    output     = args.output     or _default_output_dir()
    out_dir    = output if output.endswith("/") else output.rsplit("/", 1)[0] + "/"

    print_script_header(
        action="Running notation LLM batch",
        params={
            "input":       input_path,
            "output":      out_dir,
            "api-key-env": args.api_key_env,
            "base-url":    args.base_url,
        },
    )

    run_batch(input_path, out_dir, _state_path(), make_client(args.api_key_env, args.base_url))
