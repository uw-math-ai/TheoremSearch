"""
Submit a prepared dependency JSONL batch to the Nebius Token Factory Batch API.

Usage:
    python -m pipeline.parse_dependencies --method llm --batch run
    python -m pipeline.parse_dependencies --method judge --batch run
    python -m pipeline.parse_dependencies --method llm --batch run -i s3://bucket/notation_batches/input/ -o s3://bucket/notation_batches/output/
"""

from argparse import ArgumentParser
from pathlib import Path

from pipeline.nebius_batch import make_client, run_batch, _DEFAULT_BASE_URL, _DEFAULT_KEY_ENV
from .prepare import _s3_input_dir, _s3_output_dir, _state_path
from ...printing import print_script_header


if __name__ == "__main__":
    parser = ArgumentParser(description="Submit a dependency JSONL batch to Nebius.")
    parser.add_argument("-M", "--method", required=True, choices=["llm", "judge"],
                        help="Which batch to submit: llm or judge.")
    parser.add_argument("-i", "--input", type=str, default=None, dest="input_path")
    parser.add_argument("-o", "--output", type=str, default=None)
    parser.add_argument("--api-key-env", type=str, default=_DEFAULT_KEY_ENV, dest="api_key_env")
    parser.add_argument("--base-url", type=str, default=_DEFAULT_BASE_URL, dest="base_url")

    args = parser.parse_args()

    input_path = args.input_path or _s3_input_dir(args.method)
    output     = args.output     or _s3_output_dir(args.method)
    out_dir    = output if output.endswith("/") else output.rsplit("/", 1)[0] + "/"

    print_script_header(
        action=f"Running {args.method} batch",
        params={
            "input":       input_path,
            "output":      out_dir,
            "api-key-env": args.api_key_env,
            "base-url":    args.base_url,
        },
    )

    run_batch(input_path, out_dir, _state_path(args.method),
              make_client(args.api_key_env, args.base_url))
