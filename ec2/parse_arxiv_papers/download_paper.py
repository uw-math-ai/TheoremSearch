from typing import Tuple
import boto3
import os
import io
import gzip
import tarfile
import zipfile

ARXIV_BUCKET = "arxiv"
s3 = boto3.client("s3")

def download_paper(
    s3_loc: Tuple[str, int, int], 
    dest_dir: str
) -> str:
    bundle_tar, bytes_start, bytes_end = s3_loc
    byte_range = f"bytes={bytes_start}-{bytes_end}"

    src_path = os.path.join(
        dest_dir,
        f"{os.path.basename(bundle_tar)}.{bytes_start}-{bytes_end}.gz"
    )

    res = s3.get_object(
        Bucket=ARXIV_BUCKET,
        Key=bundle_tar,
        Range=byte_range,
        RequestPayer="requester"
    )

    body = res["Body"]

    with open(src_path, "wb") as src_f:
        for chunk in iter(lambda: body.read(8192), b""):
            src_f.write(chunk)

    return src_path

def extract_arxiv_src(src_gz_path: str, src_dir: str) -> None:
    os.makedirs(src_dir, exist_ok=True)

    with open(src_gz_path, "rb") as f:
        head = f.read(8)
        f.seek(0)
        data = f.read()

    # Helper: try extract tar bytes
    def _try_extract_tar(buf: bytes) -> bool:
        try:
            with tarfile.open(fileobj=io.BytesIO(buf), mode="r:*") as tf:
                tf.extractall(path=src_dir)
            return True
        except tarfile.ReadError:
            return False

    # 1) If it's a ZIP, extract zip
    if head.startswith(b"PK\x03\x04"):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            zf.extractall(src_dir)
        return

    # 2) Try as tar directly (covers plain tar, tar.gz if fileobj handles it)
    if _try_extract_tar(data):
        return

    # 3) If it looks gzipped, gunzip then try tar
    if head.startswith(b"\x1f\x8b"):
        try:
            unzipped = gzip.decompress(data)
        except OSError as e:
            raise RuntimeError(f"gzip decompress failed: {e!r}") from e

        if _try_extract_tar(unzipped):
            return

        # 4) gzipped but not a tar: probably a single .tex (or .sty, etc.)
        # Write it out so your pipeline can continue.
        out_path = os.path.join(src_dir, "main.tex")
        with open(out_path, "wb") as out:
            out.write(unzipped)
        return

    # 5) Not tar, not gz, not zip → write raw as main.tex so you can inspect
    out_path = os.path.join(src_dir, "main.tex")
    with open(out_path, "wb") as out:
        out.write(data)
    raise RuntimeError("Unknown archive format; wrote raw payload to src_dir/main.tex")
