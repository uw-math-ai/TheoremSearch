"""
Phase 2: Submit a prepared slogan JSONL batch to the Nebius Token Factory Batch API.

Each (model, prompt) pair has its own S3 subfolder + state file, so multiple
pairs can be in flight at the same time without collisions.

Run:
    python -m pipeline.generate_slogans.batch.run -p context-0 -m qwen3-235b
    python -m pipeline.generate_slogans.batch.run -p context-0 -m qwen3-235b \\
        -i s3://bucket/slogan_batches/qwen3-235b+context-0/input/ \\
        -o s3://bucket/slogan_batches/qwen3-235b+context-0/output/

Check progress / download results:
    python -m pipeline.generate_slogans.batch.poll -p context-0 -m qwen3-235b [--download]
"""

from argparse import ArgumentParser

from pipeline.nebius_batch import make_client, run_batch, _DEFAULT_BASE_URL, _DEFAULT_KEY_ENV
from .prepare import _default_input_dir, _default_output_dir, _state_path
from ...printing import print_script_header


if __name__ == "__main__":
    parser = ArgumentParser(
        description="Submit a slogan JSONL batch to the Nebius Token Factory Batch API."
    )
    parser.add_argument("-p", "--prompt", required=True, dest="prompt_name",
                        help="Prompt name used when preparing the batch (e.g. context-0).")
    parser.add_argument("-m", "--model", required=True, dest="model_name",
                        help="Model name used when preparing the batch (e.g. qwen3-235b).")
    parser.add_argument("-i", "--input", type=str, default=None, dest="input_path",
                        help="Input JSONL or S3 directory. Defaults to the per-pair S3 input dir.")
    parser.add_argument("-o", "--output", type=str, default=None,
                        help="Output S3 prefix or local directory. Defaults to the per-pair S3 output dir.")
    parser.add_argument("--api-key-env", type=str, default=_DEFAULT_KEY_ENV, dest="api_key_env",
                        help=f"Env var holding the API key (default: {_DEFAULT_KEY_ENV}).")
    parser.add_argument("--base-url", type=str, default=_DEFAULT_BASE_URL, dest="base_url",
                        help=f"API base URL (default: {_DEFAULT_BASE_URL}).")

    args = parser.parse_args()

    input_path = args.input_path or _default_input_dir(args.model_name, args.prompt_name)
    output     = args.output     or _default_output_dir(args.model_name, args.prompt_name)
    out_dir    = output if output.endswith("/") else output.rsplit("/", 1)[0] + "/"

    print_script_header(
        action="Running slogan LLM batch",
        params={
            "prompt":      args.prompt_name,
            "model":       args.model_name,
            "input":       input_path,
            "output":      out_dir,
            "api-key-env": args.api_key_env,
            "base-url":    args.base_url,
        },
    )

    run_batch(input_path, out_dir,
              _state_path(args.model_name, args.prompt_name),
              make_client(args.api_key_env, args.base_url))
