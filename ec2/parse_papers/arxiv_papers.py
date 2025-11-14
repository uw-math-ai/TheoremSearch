import boto3
from typing import Optional, Iterator
import tempfile, os, shutil, tarfile

s3 = boto3.client("s3")
bucket = "arxiv"

def _get_arxiv_bundle_keys(start_bundle_key: Optional[str]) -> Iterator[str]:
    all_keys = []

    paginator = s3.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=bucket, Prefix="src/", RequestPayer="requester"):
        keep_going = True

        for o in page.get("Contents", []):
            key = o["Key"]
            
            if key.endswith(".tar"):
                all_keys.append(key)

                if key == start_bundle_key:
                    keep_going = False
                    break

        if not keep_going:
            break

    all_keys.reverse()

    for key in all_keys:
        yield key

def get_arxiv_papers(
    start_bundle_key: Optional[str] = None
) -> Iterator[str]:
    for bundle_key in _get_arxiv_bundle_keys(start_bundle_key):
        bundle_res = s3.get_object(Bucket=bucket, Key=bundle_key, RequestPayer="requester")
        bundle_body = bundle_res["Body"]

        with tarfile.open(fileobj=bundle_body, mode="r|*") as bundle_tar:
            with tempfile.TemporaryDirectory() as tmpdir:
                for paper_member in bundle_tar:
                    if not paper_member.isfile():
                        continue

                    name = paper_member.name

                    if not name.endswith(".gz"):
                        continue

                    paper_tar = bundle_tar.extractfile(paper_member)
                    if paper_tar is None:
                        continue

                    paper_filename = os.path.basename(name)
                    paper_path = os.path.join(tmpdir, paper_filename)

                    with open(paper_path, "wb") as out_f:
                        shutil.copyfileobj(paper_tar, out_f)

                    yield paper_path

                    os.remove(paper_path)