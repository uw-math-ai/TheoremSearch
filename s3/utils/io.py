"""Shared S3 I/O helpers for batch pipelines."""

import tempfile
from pathlib import Path
from typing import List, Tuple

import boto3


def parse_uri(uri: str) -> Tuple[str, str]:
    """Parse s3://bucket/key → (bucket, key)."""
    without_scheme = uri[len("s3://"):]
    bucket, _, key = without_scheme.partition("/")
    return bucket, key


def list_files(prefix: str) -> List[str]:
    """Return sorted list of s3:// URIs under the given s3:// prefix."""
    bucket, key = parse_uri(prefix)
    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    uris = []
    for page in paginator.paginate(Bucket=bucket, Prefix=key):
        for obj in page.get("Contents", []):
            uris.append(f"s3://{bucket}/{obj['Key']}")
    return sorted(uris)


def clear_folder(prefix: str) -> None:
    """Delete all objects under the given s3:// prefix."""
    bucket, key = parse_uri(prefix)
    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    to_delete = []
    for page in paginator.paginate(Bucket=bucket, Prefix=key):
        for obj in page.get("Contents", []):
            to_delete.append({"Key": obj["Key"]})
    if to_delete:
        s3.delete_objects(Bucket=bucket, Delete={"Objects": to_delete})


def download_to_tmp(uri: str) -> Path:
    """Download an s3:// URI to a temp file; raises FileNotFoundError on failure."""
    bucket, key = parse_uri(uri)
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


def indexed_path(output_str: str, index: int) -> str:
    """Return an indexed file path for multi-file outputs."""
    if output_str.endswith("/"):
        return f"{output_str}{index:03d}.jsonl"
    if output_str.startswith("s3://"):
        base, _, name = output_str.rpartition("/")
        stem, dot, ext = name.rpartition(".")
        return f"{base}/{stem}_{index:04d}.{ext}" if dot else f"{base}/{name}_{index:04d}"
    p = Path(output_str)
    return str(p.parent / f"{p.stem}_{index:04d}{p.suffix}")


def open_output(dest: str):
    """Open a writable file handle; uses a temp file for s3:// destinations.

    Returns (local_path, file_handle). Call finalize_output when done.
    """
    if dest.startswith("s3://"):
        tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        tmp.close()
        local = Path(tmp.name)
    else:
        local = Path(dest)
    return local, local.open("w", encoding="utf-8")


def finalize_output(f_out, local_path: Path, dest: str) -> None:
    """Close the file handle and upload to S3 if dest is an s3:// URI."""
    f_out.close()
    if dest.startswith("s3://"):
        bucket, key = parse_uri(dest)
        boto3.client("s3").upload_file(str(local_path), bucket, key)
        local_path.unlink()


def upload_file(local_path: str | Path, dest: str) -> None:
    """Upload a local file to an s3:// URI."""
    if not dest.startswith("s3://"):
        raise ValueError(f"Destination must be an s3:// URI, got: {dest}")
    bucket, key = parse_uri(dest)
    boto3.client("s3").upload_file(str(local_path), bucket, key)


def write_text(content: str, dest: str) -> None:
    """Write text to a local path or upload to an s3:// URI."""
    if dest.startswith("s3://"):
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8")
        tmp.write(content)
        tmp.close()
        local = Path(tmp.name)
        bucket, key = parse_uri(dest)
        boto3.client("s3").upload_file(str(local), bucket, key)
        local.unlink()
        print(f"  Results uploaded to {dest}")
    else:
        Path(dest).write_text(content, encoding="utf-8")
        print(f"  Results written to {dest}")
