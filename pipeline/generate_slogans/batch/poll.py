"""
Poll submitted slogan batches and optionally download completed results.

Run anytime after run.py to check status:
    python -m pipeline.generate_slogans.batch.poll
    python -m pipeline.generate_slogans.batch.poll --download
    python -m pipeline.generate_slogans.batch.poll --all
"""

from argparse import ArgumentParser

from pipeline.nebius_batch import make_client, poll_batches, _DEFAULT_BASE_URL, _DEFAULT_KEY_ENV
from .run import _state_path
from ...printing import print_script_header


if __name__ == "__main__":
    parser = ArgumentParser(description="Poll submitted slogan batches and show progress.")
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
            "all":         args.all_batches,
            "cancel":      args.cancel,
            "download":    args.download,
            "api-key-env": args.api_key_env,
            "base-url":    args.base_url,
        },
    )

    poll_batches(
        _state_path(),
        make_client(args.api_key_env, args.base_url),
        download=args.download,
        all_batches=args.all_batches,
        cancel=args.cancel,
    )
