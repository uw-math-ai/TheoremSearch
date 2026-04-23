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


def poll_batches(api_key_env: str, base_url: str, download: bool):
    state_path = _state_path()

    if not state_path.exists():
        print("No active batches found. Run 'python -m pipeline.parse_dependencies.batch.run' first.")
        return

    state = json.loads(state_path.read_text())
    batches = state.get("batches", [])

    if not batches:
        print("No batches in state file.")
        state_path.unlink(missing_ok=True)
        return

    client = _make_client(api_key_env, base_url)

    col = f"{'Batch ID':<32}  {'Status':<12}  {'Done':>6}  {'Total':>6}  {'Failed':>6}  Output"
    print(col)
    print("-" * len(col))

    downloaded_ids = set()
    for b in batches:
        result = client.batches.retrieve(b["batch_id"])
        b["status"] = result.status
        c = result.request_counts

        print(
            f"{b['batch_id']:<32}  {result.status:<12}  {c.completed:>6}  {c.total:>6}  {c.failed:>6}  {b['output_file']}"
        )

        if result.status not in _TERMINAL_STATUSES:
            continue

        if result.status == "completed":
            if download:
                _download_results(client, result, b["output_file"])
                downloaded_ids.add(b["batch_id"])
        else:
            print(f"  Warning: batch ended with status '{result.status}' — check dashboard.")

    if download:
        batches = [b for b in batches if b["batch_id"] not in downloaded_ids]

    if batches:
        _save_state(state_path, {"batches": batches})
    else:
        state_path.unlink(missing_ok=True)
        print("\nAll batches downloaded. State file cleared.")


if __name__ == "__main__":
    arg_parser = ArgumentParser(
        description="Poll submitted concept-extraction batches and show progress."
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
            "download":    args.download,
            "api-key-env": args.api_key_env,
            "base-url":    args.base_url,
        },
    )

    poll_batches(
        api_key_env=args.api_key_env,
        base_url=args.base_url,
        download=args.download,
    )
