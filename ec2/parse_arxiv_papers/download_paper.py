from typing import Tuple
import boto3
import os

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
