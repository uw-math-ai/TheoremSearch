"""
Locates the tar bundle and position of every paper from 'paper' table in the RDS. Saves its
location under the 'paper_arxiv_s3_location' in the same table.
"""
import boto3
import tarfile
import tempfile
import re
from ..rds.connect import get_rds_connection
from ..rds.upsert import upsert_rows
from tqdm import tqdm
from typing import Optional
import argparse

ARXIV_BUCKET = "arxiv"


def _normalize_arxiv_id(paper_id: str) -> str:
    return re.sub(r"v\d+$", "", paper_id)


def _to_arxiv_id(paper_id: str) -> str:
    if "/" in paper_id:
        paper_id = paper_id.split("/", 1)[1]

    paper_id = re.sub(r"^([a-zA-Z-]+)(\d+)$", r"\1/\2", paper_id)

    return paper_id


def _get_tar_bundles_count(paginator) -> int:
    n = 0
    for bundle_page in paginator.paginate(
        Bucket=ARXIV_BUCKET,
        Prefix="src/",
        RequestPayer="requester",
    ):
        for bundle_object in bundle_page.get("Contents", []):
            bundle_key = bundle_object["Key"]
            if bundle_key.startswith("src/arXiv_src") and bundle_key.endswith(".tar"):
                n += 1
    return n


def locate_arxiv_in_s3(bundle_start: int = 0):
    print(f"=== Locating papers in arXiv S3 bucket (Bundle start: {bundle_start}) ===")

    conn = get_rds_connection()

    with conn.cursor() as cur:
        cur.execute("""
            SELECT paper_id
            FROM paper
        """)
        paper_ids = {
            _normalize_arxiv_id(row[0]): row[0]
            for row in cur.fetchall()
        }

    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    bundle_i = -1

    total_bundles = _get_tar_bundles_count(paginator)

    with tqdm(total=total_bundles) as pbar:
        for bundle_page in paginator.paginate(
            Bucket=ARXIV_BUCKET,
            Prefix="src/",
            RequestPayer="requester",
        ):
            if not paper_ids:
                break

            for bundle_object in bundle_page.get("Contents", []):
                bundle_key = bundle_object["Key"]

                if not (
                    bundle_key.startswith("src/arXiv_src")
                    and bundle_key.endswith(".tar")
                ):
                    continue

                bundle_i += 1

                if bundle_i < bundle_start:
                    pbar.update(1)
                    continue

                paper_locations = []

                with tempfile.NamedTemporaryFile() as tmp:
                    s3.download_fileobj(
                        ARXIV_BUCKET,
                        bundle_key,
                        tmp,
                        ExtraArgs={"RequestPayer": "requester"},
                    )
                    tmp.flush()
                    tmp.seek(0)

                    with tarfile.open(fileobj=tmp, mode="r:*") as bundle_tar:
                        for member in bundle_tar:
                            if not member.isfile() or not member.name.endswith(".gz"):
                                continue

                            # member.name is something like "0003/quant-ph0003119.gz"
                            member_id = member.name[:-3]  # drop ".gz"
                            paper_id_norm = _normalize_arxiv_id(
                                _to_arxiv_id(member_id)
                            )

                            if paper_id_norm in paper_ids:
                                bytes_start = member.offset_data
                                bytes_end = bytes_start + member.size - 1

                                paper_locations.append({
                                    "paper_id": paper_ids[paper_id_norm],
                                    "bundle_tar": bundle_key,
                                    "bytes_start": bytes_start,
                                    "bytes_end": bytes_end,
                                })

                                # Remove so we don't look for it again
                                del paper_ids[paper_id_norm]

                if paper_locations:
                    with conn.cursor() as cur:
                        upsert_rows(
                            cur,
                            table="paper_arxiv_s3_location",
                            rows=paper_locations,
                            on_conflict={
                                "with": ["paper_id"],
                                "replace": ["bundle_tar", "bytes_start", "bytes_end"],
                            },
                        )
                    conn.commit()

                pbar.update(1)

                yield bundle_i, bundle_key

                if not paper_ids:
                    break

            if not paper_ids:
                break

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--bundle-start",
        type=int,
        required=False,
        default=0,
        help="The first tar bundle index in the arXiv S3 bucket to look through (0-based)",
    )

    args = parser.parse_args()

    bundle_key: Optional[str] = None
    bundle_i: int = args.bundle_start - 1

    try:
        for bundle_i, bundle_key in locate_arxiv_in_s3(
            bundle_start=args.bundle_start
        ):
            pass
    except KeyboardInterrupt:
        print(
            f"[KeyboardInterrupt] Stopped after bundle #{bundle_i} "
            f"({bundle_key})"
        )