"""Nebius batch output JSONL iterator, shared across all batch inference pipelines."""

import json
import tempfile
from pathlib import Path
from typing import Iterator, List, Tuple

import boto3

from .io import parse_uri


def iter_batch_results(paths: List[str], stats: dict = None) -> Iterator[Tuple[str, str, dict]]:
    """Yield (custom_id, llm_text, usage) from Nebius batch output JSONL paths.

    Paths may be local file paths or s3:// URIs. Skips malformed/errored entries
    and raises ValueError if no valid results are found. If `stats` is provided it
    is mutated with running "skipped" and "yielded" counts (no warnings are printed).
    """
    _stats = stats if stats is not None else {}
    _stats.setdefault("skipped", 0)
    _stats.setdefault("yielded", 0)
    skipped = yielded = 0

    for path in paths:
        is_s3 = path.startswith("s3://")
        if is_s3:
            bucket, key = parse_uri(path)
            tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
            tmp.close()
            try:
                boto3.client("s3").download_file(bucket, key, tmp.name)
            except Exception as e:
                Path(tmp.name).unlink(missing_ok=True)
                raise FileNotFoundError(f"Could not download {path}: {e}")
            local_path = Path(tmp.name)
        else:
            local_path = Path(path)
            if not local_path.exists():
                raise FileNotFoundError(f"Results file not found: {path}")

        try:
            with local_path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        skipped += 1; _stats["skipped"] += 1
                        continue

                    custom_id = obj.get("custom_id", "").strip()
                    if not custom_id:
                        skipped += 1; _stats["skipped"] += 1
                        continue

                    error = obj.get("error")
                    if error:
                        skipped += 1; _stats["skipped"] += 1
                        continue

                    response = obj.get("response") or {}
                    status   = response.get("status_code")
                    if status is not None:
                        if status != 200:
                            skipped += 1; _stats["skipped"] += 1
                            continue
                        body = response.get("body") or {}
                    else:
                        body = response

                    try:
                        text = body["choices"][0]["message"]["content"]
                    except (KeyError, IndexError, TypeError):
                        skipped += 1; _stats["skipped"] += 1
                        continue

                    yield custom_id, text, body.get("usage") or {}
                    yielded += 1; _stats["yielded"] += 1
        finally:
            if is_s3:
                local_path.unlink(missing_ok=True)

    if yielded == 0:
        detail = f"{skipped} entries skipped due to errors." if skipped else "Files may be empty."
        raise ValueError(f"No valid results found. {detail}")
