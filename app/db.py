import streamlit as st
import json
import os
import boto3
import psycopg2
from psycopg2.extensions import connection
from pgvector.psycopg2 import register_vector
from dotenv import load_dotenv

load_dotenv()

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

@st.cache_data(ttl=60*60*24) # cache for 24 hours
def load_authors(_conn):
    cur = _conn.cursor()
    cur.execute("""
        SELECT DISTINCT unnest(authors)
        FROM theorem_search_qwen
        WHERE authors IS NOT NULL;
    """)

    authors = sorted(row[0] for row in cur.fetchall() if row[0])
    cur.close()
    return authors

@st.cache_data(ttl=60*60*24) # cache for 24 hours
def load_tags_per_source(_conn):
    cur = _conn.cursor()
    cur.execute("""
        SELECT source, primary_category
        FROM theorem_search_qwen
        WHERE primary_category IS NOT NULL;
    """)
    from collections import defaultdict
    tags_per_source = defaultdict(set)
    for source, category in cur.fetchall():
        if source and category:
            tags_per_source[source].add(category)
    cur.close()
    return {src: sorted(tags) for src, tags in tags_per_source.items()}

@st.cache_data(ttl=60*60*24) # cache for 24 hours
def load_theorem_count(_conn):
    cur = _conn.cursor()
    cur.execute("SELECT COUNT(*) FROM theorem_search_qwen;")
    count = cur.fetchone()[0]
    cur.close()
    return count

def row_to_dict(cursor, row):
    return {desc[0]: row[i] for i, desc in enumerate(cursor.description)}

def insert_feedback(conn, payload: dict):
    sql = """
        INSERT INTO feedback (
            feedback,
            query,
            url,
            theorem_name,
            authors,
            types,
            tags,
            sources,
            paper_filter,
            year_range,
            citation_range,
            citation_weight,
            include_unknown_citations,
            top_k
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
    """
    with conn.cursor() as cur:
        cur.execute(sql, (
            payload["feedback"],
            payload["query"],
            payload["url"],
            payload["theorem_name"],
            payload["authors"],
            payload["types"],
            payload["tags"],
            payload["sources"],
            payload["paper_filter"],
            payload["year_range"],
            payload["citation_range"],
            payload["citation_weight"],
            payload["include_unknown_citations"],
            payload["top_k"],
        ))
    conn.commit()

def serialize_filters(filters: dict) -> dict:
    return {
        "types": ",".join(filters.get("types", [])),
        "tags": ",".join(filters.get("tags", [])),
        "sources": ",".join(filters.get("sources", [])),
        "paper_filter": ",".join(
            list(filters.get("paper_filter", {}).get("ids", [])) +
            list(filters.get("paper_filter", {}).get("titles", []))
        ),
        "year_range": (
            f"{filters['year_range'][0]}–{filters['year_range'][1]}"
            if filters.get("year_range") else None
        ),
        "citation_range": (
            f"{filters['citation_range'][0]}–{filters['citation_range'][1]}"
            if filters.get("citation_range") else None
        ),
        "citation_weight": float(filters.get("citation_weight", 0.0)),
        "include_unknown_citations": str(filters.get("include_unknown_citations")),
        "top_k": int(filters.get("top_k", 0)),
    }
