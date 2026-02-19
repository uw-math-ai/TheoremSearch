from argparse import ArgumentParser
from ..printing.scripts import print_script_header
from ..rds.connect import get_rds_connection
from ..rds.paginate import paginate_query
from ..rds.query import get_query_count
from tqdm import tqdm
from tempfile import TemporaryFile
from typing import List
import csv
import boto3
import io


def download_table(table: str, order_by: str, condition: str, s3_uri: str):
    print_script_header(
        action=f"Downloading {table} table",
        params={"table": table, "condition?": condition}
    )

    conn = get_rds_connection()

    # Build query
    query = f"SELECT * FROM {table}"
    if condition:
        query += f" WHERE {condition}"

    count = get_query_count(conn, query)

    cols: List[str] = []

    with tqdm(total=count, dynamic_ncols=True) as pbar, TemporaryFile(mode="w+b") as tf_bin:
        # Wrap the binary temp file in a text layer for csv writing
        tf_text = io.TextIOWrapper(tf_bin, encoding="utf-8", newline="")
        writer = csv.writer(tf_text, quoting=csv.QUOTE_MINIMAL)

        for rows in paginate_query(conn, base_query=query, order_by=order_by, page_size=1000):
            if not rows:
                continue

            if not cols:
                cols = list(rows[0].keys())
                writer.writerow(cols)

            writer.writerows(
                ["" if row.get(col) is None else str(row.get(col)) for col in cols]
                for row in rows
            )

            pbar.update(len(rows))

        # IMPORTANT: flush the text wrapper into the underlying binary file
        tf_text.flush()

        # Rewind the *binary* file for upload
        tf_bin.seek(0)

        # Upload (must pass the binary file object)
        if not s3_uri.startswith("s3://"):
            raise ValueError("s3_uri must look like s3://bucket/key")

        _, _, bucket_and_key = s3_uri.partition("s3://")
        bucket, _, key = bucket_and_key.partition("/")

        s3 = boto3.client("s3")
        s3.upload_fileobj(tf_bin, bucket, key)

        # Optional but tidy: detach wrapper so it doesn't close tf_bin unexpectedly on exit
        try:
            tf_text.detach()
        except:
            pass

    conn.close()


if __name__ == "__main__":
    arg_parser = ArgumentParser()
    arg_parser.add_argument("--table", type=str, required=True)
    arg_parser.add_argument("--order-by", type=str, required=True)
    arg_parser.add_argument("--condition", type=str, required=False, default="")
    arg_parser.add_argument("--s3-uri", type=str, required=True)

    args = arg_parser.parse_args()

    download_table(
        table=args.table,
        order_by=args.order_by,
        condition=args.condition,
        s3_uri=args.s3_uri,
    )
