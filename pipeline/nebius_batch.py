"""
Shared Nebius Token Factory Batch API helpers.

Used by any pipeline that follows the prepare → run → poll → connect pattern.
Each pipeline's run.py and poll.py are thin wrappers that supply the
pipeline-specific state file path and S3 defaults, then delegate here.
"""

import json
import os
from pathlib import Path

from openai import OpenAI

from s3.utils.io import clear_folder, list_files, download_to_tmp, write_text

_DEFAULT_BASE_URL  = "https://api.tokenfactory.nebius.com/v1/"
_DEFAULT_KEY_ENV   = "NEBIUS_API_KEY"
_TERMINAL_STATUSES = {"completed", "failed", "expired", "cancelled"}


def make_client(api_key_env: str, base_url: str) -> OpenAI:
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise EnvironmentError(
            f"Environment variable {api_key_env!r} is not set.\n"
            f"Run: export {api_key_env}=<your-api-key>"
        )
    return OpenAI(api_key=api_key, base_url=base_url)


def save_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, indent=2))


def _submit_one(client: OpenAI, local_input: Path) -> str:
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


def run_batch(input_path: str, out_dir: str, state_path: Path, client: OpenAI) -> None:
    """Submit input JSONL file(s) to Nebius and persist batch IDs to state_path."""
    if out_dir.startswith("s3://"):
        print(f"Clearing {out_dir} ...")
        clear_folder(out_dir)

    if input_path.startswith("s3://") and input_path.endswith("/"):
        input_uris = list_files(input_path)
        if not input_uris:
            raise FileNotFoundError(f"No files found in {input_path}")
    else:
        if not input_path.startswith("s3://") and not Path(input_path).exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")
        input_uris = [input_path]

    if len(input_uris) > 1:
        print(f"Found {len(input_uris)} input file(s); submitting {len(input_uris)} batches.")

    batches = []
    for i, uri in enumerate(input_uris):
        out_file = f"{out_dir}{i:03d}.jsonl"
        is_s3 = uri.startswith("s3://")
        if is_s3:
            print(f"[{i+1}/{len(input_uris)}] Downloading {uri} ...")
            local_input = download_to_tmp(uri)
        else:
            local_input = Path(uri)
            if local_input.stat().st_size == 0:
                raise ValueError(f"Input file is empty: {uri}")
        try:
            print(f"[{i+1}/{len(input_uris)}] Submitting batch ...")
            batch_id = _submit_one(client, local_input)
        finally:
            if is_s3:
                local_input.unlink(missing_ok=True)
        batches.append({"batch_id": batch_id, "status": "in_progress", "output_file": out_file})
        save_state(state_path, {"batches": batches})

    print(f"\nSubmitted {len(batches)} batch(es). Run poll.py to check progress and download results.")


_ID_WIDTH = 46


def _print_error_file(client, batch) -> None:
    """Fetch and print per-request errors from the batch error file."""
    if not batch.error_file_id:
        print("  (no error file available)")
        return
    print(f"  Error file ({batch.error_file_id}):")
    try:
        errors = client.files.content(batch.error_file_id).text
        for line in errors.strip().splitlines():
            print(f"    {line}")
    except Exception as e:
        print(f"  Could not fetch error file: {e}")


def _download_results(client, batch, output: str) -> None:
    if batch.status != "completed":
        errors = getattr(batch, "errors", None)
        print(
            f"  Batch {batch.id} ended with status '{batch.status}'."
            + (f"\n  Batch-level errors: {errors}" if errors else "")
        )
        _print_error_file(client, batch)
        return
    if not batch.output_file_id:
        print(
            f"  Batch {batch.id} completed but produced no output file — "
            f"all {batch.request_counts.total} request(s) likely failed."
        )
        _print_error_file(client, batch)
        return
    print(f"  Downloading results (file: {batch.output_file_id}) ...")
    content = client.files.content(batch.output_file_id).text
    write_text(content, output)
    print(f"  {content.count(chr(10))} result lines total.")
    if batch.request_counts.failed > 0:
        print(f"  Warning: {batch.request_counts.failed} request(s) failed.")
        _print_error_file(client, batch)


def poll_batches(
    state_path: Path,
    client: OpenAI,
    download: bool,
    all_batches: bool,
    cancel: bool,
) -> None:
    """Show status of submitted batches; optionally download completed results or cancel."""
    state_batches = []
    if state_path.exists():
        state_batches = json.loads(state_path.read_text()).get("batches", [])
    output_file_by_id = {b["batch_id"]: b["output_file"] for b in state_batches}

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
        elif batch.status in _TERMINAL_STATUSES and download:
            if out == "—":
                print(f"  Skipping: no output path in state file for {batch.id}")
            else:
                _download_results(client, batch, out)
                downloaded_ids.add(batch.id)
        elif batch.status in _TERMINAL_STATUSES and batch.status != "completed":
            _print_error_file(client, batch)

    removed_ids = downloaded_ids | cancelled_ids
    if removed_ids:
        remaining = [b for b in state_batches if b["batch_id"] not in removed_ids]
        if remaining:
            save_state(state_path, {"batches": remaining})
        else:
            state_path.unlink(missing_ok=True)
            print("\nState file cleared.")
