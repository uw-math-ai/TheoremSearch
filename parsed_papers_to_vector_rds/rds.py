import os
import json
import psycopg2
import boto3
from psycopg2.extensions import connection

def get_rds_connection() -> connection:
    region = os.getenv("AWS_REGION", "us-west-2")
    secret_arn = os.getenv("RDS_SECRET_ARN")
    host = os.getenv("RDS_HOST", "")
    dbname = "postgres"

    sm = boto3.client("secretsmanager", region_name=region)
    secret_value = sm.get_secret_value(SecretId=secret_arn)
    secret_dict = json.loads(secret_value["SecretString"])

    conn = psycopg2.connect(
        host=host or secret_dict.get("host"),
        port=int(secret_dict.get("port", 5432)),
        dbname=dbname or secret_dict.get("dbname", "postgres"),
        user=secret_dict["username"],
        password=secret_dict["password"],
        sslmode="require",
    )
    return conn


def upload_theorem_metadata_and_embeddings(
    conn: connection,
    theorem_metadata: dict,
    theorem_embeddings: list[dict]
):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO theorem_metadata
                (title, authors, link, last_updated, summary,
                 journal_ref, primary_category, categories,
                 global_notations, global_definitions, global_assumptions)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING paper_id;
        """, (
            theorem_metadata.get("title"),
            theorem_metadata.get("authors"),
            theorem_metadata.get("link"),
            theorem_metadata.get("last_updated"),
            theorem_metadata.get("summary"),
            theorem_metadata.get("journal_ref"),
            theorem_metadata.get("primary_category"),
            theorem_metadata.get("categories"),
            theorem_metadata.get("global_notations"),
            theorem_metadata.get("global_definitions"),
            theorem_metadata.get("global_assumptions"),
        ))

        paper_id = cur.fetchone()[0]
        
        for th in theorem_embeddings:
            cur.execute("""
                INSERT INTO theorem_embedding
                    (paper_id, theorem_name, theorem_body, embedding)
                VALUES (%s, %s, %s, %s);
            """, (
                paper_id,
                th.get("theorem_name"),
                th.get("theorem_body"),
                th.get("embedding"),
            ))

    conn.commit()
