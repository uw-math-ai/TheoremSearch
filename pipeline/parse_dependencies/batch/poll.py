"""
Phase 2b: Check progress of submitted batches and optionally download completed results.

Run:
    python -m pipeline.parse_dependencies.batch.poll
    python -m pipeline.parse_dependencies.batch.poll --download
"""

import json
import tempfile
from argparse import ArgumentParser
from pathlib import Path

import boto3

from .run import _make_client, _save_state, _state_path, _DEFAULT_KEY_ENV, _DEFAULT_BASE_URL

_TERMINAL_STATUSES = {"completed", "failed", "expired", "cancelled"}
from .prepare import _parse_s3_uri
from ...printing import print_script_header


def _write_output(content: str, output: str):
    if output.startswith("s3://"):
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8")
        tmp.write(content)
        tmp.close()
        local = Path(tmp.name)
        bucket, key = _parse_s3_uri(output)
        boto3.client("s3").upload_file(str(local), bucket, key)
        local.unlink()
        print(f"  Results uploaded to {output}")
    else:
        Path(output).write_text(content, encoding="utf-8")
        print(f"  Results written to {output}")


def _download_results(client, batch, output: str):
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

    print(f"  Downloading results (file: {batch.output_file_id}) ...")
    content = client.files.content(batch.output_file_id).text
    _write_output(content, output)
    print(f"  {content.count(chr(10))} result lines total.")

    if batch.request_counts.failed > 0:
        print(
            f"  Warning: {batch.request_counts.failed} request(s) failed.\n"
            f"  Error file ID: {batch.error_file_id}"
        )


_ID_WIDTH = 46  # Nebius batch IDs are ~43 chars


def poll_batches(api_key_env: str, base_url: str, download: bool, all_batches: bool, cancel: bool):
    state_path = _state_path()
    state_batches = []
    if state_path.exists():
        state_batches = json.loads(state_path.read_text()).get("batches", [])
    output_file_by_id = {b["batch_id"]: b["output_file"] for b in state_batches}

    client = _make_client(api_key_env, base_url)

    if all_batches:
        batches = list(client.batches.list())
    else:
        if not state_batches:
            print("No batches in state file. Run with --all to list all account batches.")
            return
        batches = [client.batches.retrieve(b["batch_id"]) for b in state_batches]

    if not batches:
        print("No batches found.")
        return

    col = f"{'Batch ID':<{_ID_WIDTH}}  {'Status':<12}  {'Done':>6}  {'Total':>6}  {'Failed':>6}  Output"
    print(col)
    print("-" * len(col))

    downloaded_ids = set()
    cancelled_ids  = set()
    for batch in batches:
        c      = batch.request_counts
        done   = (c.completed if c else None) or 0
        total  = (c.total     if c else None) or 0
        failed = (c.failed    if c else None) or 0
        out    = output_file_by_id.get(batch.id, "—")

        print(f"{batch.id:<{_ID_WIDTH}}  {batch.status:<12}  {done:>6}  {total:>6}  {failed:>6}  {out}")

        if cancel and batch.status not in _TERMINAL_STATUSES:
            client.batches.cancel(batch.id)
            print(f"  Cancelled.")
            cancelled_ids.add(batch.id)
        elif batch.status == "completed" and download:
            if out == "—":
                print(f"  Skipping: no output path in state file for {batch.id}")
            else:
                _download_results(client, batch, out)
                downloaded_ids.add(batch.id)
        elif batch.status in _TERMINAL_STATUSES and batch.status != "completed":
            if batch.error_file_id:
                errors = client.files.content(batch.error_file_id).text
                for line in errors.strip().splitlines():
                    print(f"  error: {line}")
            else:
                print(f"  Warning: batch ended with status '{batch.status}' — no error file available.")

    removed_ids = downloaded_ids | cancelled_ids
    if removed_ids:
        remaining = [b for b in state_batches if b["batch_id"] not in removed_ids]
        if remaining:
            _save_state(state_path, {"batches": remaining})
        else:
            state_path.unlink(missing_ok=True)
            print("\nState file cleared.")


if __name__ == "__main__":
    arg_parser = ArgumentParser(
        description="Poll submitted concept-extraction batches and show progress."
    )
    arg_parser.add_argument(
        "--all",
        action="store_true",
        default=False,
        dest="all_batches",
        help="List all batches on the account instead of only those in the state file.",
    )
    arg_parser.add_argument(
        "--cancel",
        action="store_true",
        default=False,
        help="Cancel all non-terminal batches.",
    )
    arg_parser.add_argument(
        "--download",
        action="store_true",
        default=False,
        help="Download results for completed batches and remove them from state.",
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
        action="Polling concepts LLM batches",
        params={
            "all":         args.all_batches,
            "cancel":      args.cancel,
            "download":    args.download,
            "api-key-env": args.api_key_env,
            "base-url":    args.base_url,
        },
    )

    poll_batches(
        api_key_env=args.api_key_env,
        base_url=args.base_url,
        download=args.download,
        all_batches=args.all_batches,
        cancel=args.cancel,
    )
