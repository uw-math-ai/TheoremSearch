"""
Parses research papers stored on S3 or elsewhere and adds paper metadata to the 'paper' table
in the RDS and theorem data to the 'theorem' table in the RDS.
"""

import boto3
import tarfile
import io
import argparse
from tqdm import tqdm
from .tex import extract_main_tex_file_content, collect_imports
import regex
from .patterns import *
from .latex_parse import extract
from .arxiv_metadata import get_paper_metadata
from ..rds import get_rds_connection

S3_BUCKET_NAME = "arxiv-full-dataset"

s3 = boto3.client("s3")
conn = get_rds_connection()

def parse_papers(
    s3_papers_dir: str,
    s3_bucket_name: str = S3_BUCKET_NAME
):
    papers_res = s3.list_objects_v2(Bucket=s3_bucket_name, Prefix=s3_papers_dir)
    paper_keys = [o["Key"] for o in papers_res.get("Contents", []) if o["Key"].endswith(".tar.gz")]

    for paper_key in tqdm(paper_keys, ncols=80):
        paper_id = paper_key.replace(".tar.gz", "").split("/")[-1].split("_")[-1]

        # TODO: Check for and handle paper_id conflicts

        paper_res = s3.get_object(Bucket=s3_bucket_name, Key=paper_key)
        paper_obj = io.BytesIO(paper_res["Body"].read())

        paper_content = None

        try:
            with tarfile.open(fileobj=paper_obj, mode="r:*") as tar:
                paper_content = extract_main_tex_file_content(tar)
        except Exception as e:
            continue

        paper_content = regex.sub(r"(?<!\\)%.*", "", paper_content)
        paper_content = regex.sub(r'\\begin\{comment\}.*?\\end\{comment\}', '', paper_content, flags=regex.DOTALL)

        with tarfile.open(fileobj=paper_obj, mode="r:*") as tar:
            import_appends = collect_imports("", tar, paper_content, NEWINPUT)
            import_appends = collect_imports(import_appends, tar, paper_content, NEWUSEPACKAGE)

        try:
            theorems = extract(paper_content, import_appends)

            paper_metadata = get_paper_metadata(paper_id)
        except Exception as e:
            continue
        
        theorem_metadatas = [
            {
                "name": thm,
                "body": body,
                "label": label
            }
            for thm, body, label in theorems
            if thm.lower().split(" ")[0] in set(["theorem", "proposition", "lemma"])
        ]

        if not theorem_metadatas:
            continue

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO paper (
                    paper_id, title, authors, link, last_updated, summary, journal_ref,
                    primary_category, categories, citations
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (paper_id) DO NOTHING;
            """, (
                paper_metadata.get("paper_id"),
                paper_metadata.get("title"),
                paper_metadata.get("authors"),
                paper_metadata.get("link"),
                paper_metadata.get("last_updated"),
                paper_metadata.get("summary"),
                paper_metadata.get("journal_ref"),
                paper_metadata.get("primary_category"),
                paper_metadata.get("categories"),
                paper_metadata.get("citations"),
            ))

            for theorem_metadata in theorem_metadatas:
                cur.execute("""
                    INSERT INTO theorem (
                        paper_id, name, body, label
                    )
                    VALUES (%s, %s, %s, %s)
                """, (
                    paper_id,
                    theorem_metadata.get("name"),
                    theorem_metadata.get("body"),
                    theorem_metadata.get("label")
                ))

        conn.commit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dir", 
        type=str, 
        required=True,
        help="The directory including papers to parse"
    )

    args = parser.parse_args()

    parse_papers(args.dir)