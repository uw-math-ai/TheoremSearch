import boto3
import psycopg2
from psycopg2.extensions import connection
from pgvector.psycopg2 import register_vector
import json
import os

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

def create_table(conn: connection):
    cur = conn.cursor()
    print("Creating search table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS theorem_search_qwen (
            slogan_id        BIGINT PRIMARY KEY,
            theorem_id       BIGINT NOT NULL,
            paper_id         TEXT   NOT NULL,
        
            embedding        vector(1024) NOT NULL,
            slogan_model     TEXT NOT NULL,
            prompt_id        TEXT NOT NULL,
        
            theorem_name     TEXT NOT NULL,
            theorem_body     TEXT NOT NULL,
            theorem_slogan   TEXT NOT NULL,
        
            title            TEXT NOT NULL,
            authors          TEXT[] NOT NULL,
            link             TEXT NOT NULL,
            year             INT,
            journal_published BOOLEAN,
            primary_category TEXT,
            categories       TEXT[],
            citations        INT,
        
            source           TEXT NOT NULL
        );
    """)
    print("Search table created.")
    conn.commit()
    cur.close()

def create_index(conn: connection):
    cur = conn.cursor()
    print("Creating index...")
    cur.execute("""
        CREATE INDEX IF NOT EXISTS theorem_search_qwen_ivfflat
        ON theorem_search_qwen
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100);
    """)
    print("Index created.")
    conn.commit()
    cur.close()

def backfill(conn: connection):
    cur = conn.cursor()
    print("Backfilling theorem_search_qwen...")
    cur.execute("""
        INSERT INTO theorem_search_qwen (
            slogan_id,
            theorem_id,
            paper_id,
            embedding,
            slogan_model,
            prompt_id,
            theorem_name,
            theorem_body,
            theorem_slogan,
            title,
            authors,
            link,
            year,
            journal_published,
            primary_category,
            categories,
            citations,
            source,
            theorem_type
        )
        SELECT
            ts.slogan_id,
            t.theorem_id,
            p.paper_id,
            e.embedding,
            ts.model,
            ts.prompt_id,        
            t.name,
            t.body,
            ts.slogan,
            p.title,
            p.authors,
            p.link,
            EXTRACT(YEAR FROM p.last_updated)::INT,
            (p.journal_ref IS NOT NULL),
            p.primary_category,
            p.categories,
            p.citations,
            CASE
                WHEN p.link ILIKE '%arxiv.org%' THEN 'arXiv'
                WHEN p.link ILIKE '%stacks.math.columbia.edu%' THEN 'Stacks Project'
                ELSE 'Other'
            END,
            CASE
                WHEN t.name ILIKE 'lemma %'        THEN 'lemma'
                WHEN t.name ILIKE 'proposition %'  THEN 'proposition'
                WHEN t.name ILIKE 'corollary %'    THEN 'corollary'
                WHEN t.name ILIKE 'theorem %'      THEN 'theorem'
                ELSE 'theorem'
            END AS theorem_type
        FROM theorem_embedding_qwen e
        JOIN theorem_slogan ts ON ts.slogan_id = e.slogan_id
        JOIN theorem t ON t.theorem_id = ts.theorem_id
        JOIN paper p ON p.paper_id = t.paper_id
        WHERE ts.model = 'DeepSeek-V3.1'
          AND ts.prompt_id = 'body-only-v1'
        ON CONFLICT (slogan_id) DO NOTHING;
    """)
    print(f"Rows inserted: {cur.rowcount}")
    conn.commit()
    cur.close()