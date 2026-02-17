import json
from tqdm import tqdm
from rds.utils.connect import get_rds_connection
from rds.utils.upsert import upsert_rows
from arXiTeX import s3_locator
from argparse import ArgumentParser
from ..printing import print_script_header

def index_arxiv_s3(batch_size: int):
    print_script_header(
        action="Indexing arXiv's S3 bucket",
        params={
            "batch size": batch_size 
        }
    )

    conn = get_rds_connection("v2")

    with conn.cursor() as cur:
        cur.execute("SELECT id from paper WHERE source = 'arXiv'")
        arxiv_ids = [row[0] for row in cur.fetchall()]

    with tqdm(total=len(arxiv_ids), unit=" locations", dynamic_ncols=True) as pbar:
        for s3_locations in s3_locator(arxiv_ids, batch_size=batch_size):
            upsert_rows(
                conn,
                table="s3_location",
                rows=[
                    json.loads(s3_location.model_dump_json()) | {
                        "source": "arXiv"
                    }
                    for s3_location in s3_locations
                ],
                on_conflict={
                    "with": ["arxiv_id", "source"],
                    "replace": ["bundle_key", "bytes_range"]
                }
            )

            conn.commit()
            pbar.update(len(s3_locations))
            
if __name__ == "__main__":
    arg_parser = ArgumentParser()

    arg_parser.add_argument(
        "-b",
        "--batch-size",
        type=int,
        required=False,
        default=128,
        help="Number of S3 locations to upsert in one batch"
    )

    args = arg_parser.parse_args()

    index_arxiv_s3(args.batch_size)