"""
Downloads all or a sample of parsed papers from the 'parsed_papers' directory of the
'arxiv-full-dataset' S3 bucket. Skips download of papers already downloaded.
"""

import boto3
import os

BUCKET_NAME = "arxiv-full-dataset"
S3_PARSED_PAPERS_DIR = "parsed_papers"
LOCAL_PAPERS_DIR = "parsed_papers"

s3 = boto3.client("s3")

def download_parsed_papers(
    n_papers: int | None = None,
    s3_bucket_name: str = BUCKET_NAME,
    s3_parsed_papers_dir: str = S3_PARSED_PAPERS_DIR,
    local_parsed_papers_dir: str = LOCAL_PAPERS_DIR
):
    os.makedirs(local_parsed_papers_dir, exist_ok=True)

    res = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix=s3_parsed_papers_dir)
    keys = [o["Key"] for o in res.get("Contents", [])]

    downloaded = 0

    for key in keys:
        if n_papers is not None and downloaded >= n_papers:
            break

        local_parsed_paper_path = os.path.join(local_parsed_papers_dir, os.path.basename(key))

        if os.path.exists(local_parsed_paper_path):
            continue
        else:
            s3.download_file(s3_bucket_name, key, local_parsed_paper_path)
            downloaded += 1

if __name__ == "__main__":
    download_parsed_papers()