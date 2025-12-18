from typing import Tuple
import boto3
import os
import io
import gzip
import tarfile
import zipfile

ARXIV_BUCKET = "arxiv"
s3 = boto3.client("s3")

def _download_paper(
    paper_id: str,
    s3_loc: Tuple[str, int, int],
    cwd: str
) -> str:
    os.makedirs(cwd, exist_ok=True)

    bundle_tar, bytes_start, bytes_end = s3_loc

    src_gz_path = os.path.join(cwd, f"{paper_id.replace('/', '-')}.gz")

    res = s3.get_object(
        Bucket=ARXIV_BUCKET,
        Key=bundle_tar,
        Range=f"bytes={bytes_start}-{bytes_end}",
        RequestPayer="requester"
    )

    body = res["Body"]

    with open(src_gz_path, "wb") as src_gz_b:
        for chunk in iter(lambda: body.read(8192), b""):
            src_gz_b.write(chunk)

    return src_gz_path

def extract_paper_src(src_gz_path: str, src_dir: str) -> None:
    os.makedirs(src_dir, exist_ok=True)

    with open(src_gz_path, "rb") as f:
        head = f.read(8)
        f.seek(0)
        data = f.read()

    def _try_extract_tar(buf: bytes) -> bool:
        try:
            with tarfile.open(fileobj=io.BytesIO(buf), mode="r:*") as tf:
                tf.extractall(path=src_dir)
            return True
        except tarfile.ReadError:
            return False

    # Handle zip
    if head.startswith(b"PK\x03\x04"):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            zf.extractall(src_dir)
        return

    # Handle tar
    if _try_extract_tar(data):
        return

    # Handle gzip
    if head.startswith(b"\x1f\x8b"):
        try:
            unzipped = gzip.decompress(data)
        except OSError as e:
            raise RuntimeError(f"gzip decompress failed: {e!r}") from e

        # Handle gzip -> tar
        if _try_extract_tar(unzipped):
            return

        # Handle gzip -> not tar
        out_path = os.path.join(src_dir, "main.tex")
        with open(out_path, "wb") as out:
            out.write(unzipped)
        return

    # Handle unknown
    out_path = os.path.join(src_dir, "main.tex")
    with open(out_path, "wb") as out:
        out.write(data)
    raise RuntimeError("Unknown archive format; wrote raw payload to src_dir/main.tex")

def download_and_extract_paper(
    paper_id: str,
    s3_loc: Tuple[str, int, int],
    cwd: str
):
    """
    Given an arXiv paper's ID and location in the S3 bucket, downloads and extracts the paper
    into the given cwd. The extracted paper TeX source, if possible, will be in the returned
    directory path (named after the ID).
    """

    src_gz_path = _download_paper(paper_id, s3_loc, cwd)
    src_dir = src_gz_path.removesuffix(".gz")

    extract_paper_src(src_gz_path, src_dir)

    return src_dir