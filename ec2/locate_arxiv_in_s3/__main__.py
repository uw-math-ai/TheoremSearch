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

def _list_tar_bundle_keys(paginator) -> list[str]:
    keys: list[str] = []
    for bundle_page in paginator.paginate(
        Bucket=ARXIV_BUCKET,
        Prefix="src/",
        RequestPayer="requester",
    ):
        for bundle_object in bundle_page.get("Contents", []):
            k = bundle_object["Key"]
            if k.startswith("src/arXiv_src") and k.endswith(".tar"):
                keys.append(k)
    return keys


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

    bundle_keys = _list_tar_bundle_keys(paginator)
    total_bundles = len(bundle_keys)

    bundle_keys = list(reversed(bundle_keys))

    with tqdm(total=total_bundles) as pbar:
        for rev_i, bundle_key in enumerate(bundle_keys):
            forward_i = total_bundles - 1 - rev_i
            if forward_i < bundle_start:
                pbar.update(1)
                continue

            if not paper_ids:
                break

            paper_locations = {}

            try:
                with tempfile.NamedTemporaryFile() as tmp:
                    s3.download_fileobj(
                        ARXIV_BUCKET,
                        bundle_key,
                        tmp,
                        ExtraArgs={"RequestPayer": "requester"},
                    )
                    tmp.flush()
                    tmp.seek(0)

                    with tarfile.open(fileobj=tmp, mode="r:") as bundle_tar:
                        for member in reversed(bundle_tar.getmembers()):
                            if not member.isfile() or not member.name.endswith(".gz"):
                                continue
                            if not getattr(member, "size", 0):
                                continue

                            try:
                                member_id = member.name[:-3]
                                paper_id_norm = _normalize_arxiv_id(_to_arxiv_id(member_id))

                                if paper_id_norm not in paper_ids:
                                    continue

                                bytes_start = getattr(member, "offset_data", None)
                                if bytes_start is None:
                                    raise RuntimeError("member.offset_data is None")

                                bytes_end = bytes_start + member.size - 1

                                tmp.seek(bytes_start)
                                if tmp.read(3) != b"\x1f\x8b\x08":
                                    raise RuntimeError(
                                        f"Bad gzip header at offset_data for {member.name} "
                                        f"(bundle={bundle_key}, off={bytes_start})"
                                    )

                                paper_locations[paper_id_norm] = {
                                    "paper_id": paper_ids[paper_id_norm],
                                    "bundle_tar": bundle_key,
                                    "bytes_start": bytes_start,
                                    "bytes_end": bytes_end,
                                }

                                del paper_ids[paper_id_norm]

                            except Exception as e:
                                print(f"[LOCATE WARN] {bundle_key} member={getattr(member, 'name', '?')}: {repr(e)[:200]}")
                                continue

            except Exception as e:
                print(f"[BUNDLE WARN] {bundle_key}: {repr(e)[:200]}")
                pbar.update(1)
                yield forward_i, bundle_key
                continue

            if paper_locations:
                with conn.cursor() as cur:
                    upsert_rows(
                        cur,
                        table="paper_arxiv_s3_location",
                        rows=list(paper_locations.values()),
                        on_conflict={
                            "with": ["paper_id"],
                            "replace": ["bundle_tar", "bytes_start", "bytes_end"],
                        },
                    )
                conn.commit()

            pbar.update(1)
            yield forward_i, bundle_key

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