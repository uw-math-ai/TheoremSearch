import csv
import json
import boto3
import psycopg2
from dotenv import load_dotenv
from pgvector.psycopg2 import register_vector
from psycopg2._psycopg import connection
from psycopg2.extras import DictCursor
import os
import re

load_dotenv()

INPUT_CSV  = "stacks_label_slogans.csv"
OUTPUT_CSV = "stacks_label_slogans_augmented.csv"

SLOGAN_BLOCK_RE = re.compile(
    r"\\begin\{slogan\}.*?\\end\{slogan\}",
    flags=re.DOTALL
)

def strip_slogan_env(latex: str) -> str:
    """
    Remove \\begin{slogan} ... \\end{slogan} blocks from theorem LaTeX.
    """
    cleaned = SLOGAN_BLOCK_RE.sub("", latex)

    # clean up extra blank lines
    cleaned = re.sub(r"\n\s*\n\s*\n", "\n\n", cleaned)

    return cleaned.strip()

def get_rds_connection() -> connection:
    region = os.getenv("AWS_REGION")
    secret_arn = os.getenv("RDS_SECRET_ARN")
    host = os.getenv("RDS_HOST")
    dbname = os.getenv("RDS_DB_NAME")

    sm = boto3.client("secretsmanager", region_name=region)
    secret_value = sm.get_secret_value(SecretId=secret_arn)
    secret_dict = json.loads(secret_value["SecretString"])

    conn = psycopg2.connect(
        host=host or secret_dict.get("host"),
        port=int(secret_dict.get("port", 5432)),
        dbname=dbname or secret_dict.get("dbname"),
        user=secret_dict["username"],
        password=secret_dict["password"],
        sslmode="require",
    )
    register_vector(conn)
    return conn

def load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def fetch_theorems_by_label(conn, labels):
    with conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute(
            """
            SELECT
                body,
                label,
                link
            FROM theorem
            WHERE label = ANY(%s) AND link IS NOT NULL
            """,
            (labels,)
        )
        return {row["label"]: dict(row) for row in cur.fetchall()}

def main():
    rows = load_csv(INPUT_CSV)
    labels = [r["label"] for r in rows]

    conn = get_rds_connection()
    theorem_data = fetch_theorems_by_label(conn, labels)
    conn.close()

    # Merge
    augmented = []
    for r in rows:
        label = r["label"]
        db_row = theorem_data.get(label, {})

        augmented.append({
            "body": strip_slogan_env(db_row.get("body")),
            "slogan": r["slogan"],
            "label": label,
            "tag": db_row.get("link")[-4:],
            "link": db_row.get("link")
        })

    # Write output
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=augmented[0].keys()
        )
        writer.writeheader()
        writer.writerows(augmented)

    print(f"Wrote {len(augmented)} rows to {OUTPUT_CSV}")

if __name__ == "__main__":
    main()
