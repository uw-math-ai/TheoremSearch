"""
Poll submitted slogan batches and optionally download completed results.

Specify the (model, prompt) pair to scope to that pair's state file. Use --all
to ignore the state file and list every batch on the account.

Run anytime after run.py to check status:
    python -m pipeline.generate_slogans.batch.poll -p context-0 -m qwen3-235b
    python -m pipeline.generate_slogans.batch.poll -p context-0 -m qwen3-235b --download
    python -m pipeline.generate_slogans.batch.poll -p context-0 -m qwen3-235b --all
"""

from argparse import ArgumentParser

from pipeline.nebius_batch import make_client, poll_batches, _DEFAULT_BASE_URL, _DEFAULT_KEY_ENV
from .prepare import _state_path
from ...printing import print_script_header


if __name__ == "__main__":
    parser = ArgumentParser(description="Poll submitted slogan batches and show progress.")
    parser.add_argument("-p", "--prompt", required=True, dest="prompt_name",
                        help="Prompt name used when preparing the batch (e.g. context-0).")
    parser.add_argument("-m", "--model", required=True, dest="model_name",
                        help="Model name used when preparing the batch (e.g. qwen3-235b).")
    parser.add_argument("--all", action="store_true", default=False, dest="all_batches",
                        help="List all batches on the account instead of only those in the state file.")
    parser.add_argument("--cancel", action="store_true", default=False,
                        help="Cancel all non-terminal batches.")
    parser.add_argument("--download", action="store_true", default=False,
                        help="Download results for completed batches and remove them from state.")
    parser.add_argument("--api-key-env", type=str, default=_DEFAULT_KEY_ENV, dest="api_key_env",
                        help=f"Env var holding the API key (default: {_DEFAULT_KEY_ENV}).")
    parser.add_argument("--base-url", type=str, default=_DEFAULT_BASE_URL, dest="base_url",
                        help=f"API base URL (default: {_DEFAULT_BASE_URL}).")

    args = parser.parse_args()

    print_script_header(
        action="Polling slogan LLM batches",
        params={
            "prompt":      args.prompt_name,
            "model":       args.model_name,
            "all":         args.all_batches,
            "cancel":      args.cancel,
            "download":    args.download,
            "api-key-env": args.api_key_env,
            "base-url":    args.base_url,
        },
    )

    poll_batches(
        _state_path(args.model_name, args.prompt_name),
        make_client(args.api_key_env, args.base_url),
        download=args.download,
        all_batches=args.all_batches,
        cancel=args.cancel,
    )
