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

@st.cache_data(ttl=60*60*24)
def load_sources(_conn):
    cur = _conn.cursor()
    cur.execute("SELECT DISTINCT source FROM theorem_search_qwen;")
    sources = cur.fetchall()
    cur.close()
    return [row[0] for row in sources]

@st.cache_data(ttl=60*60*24) # cache for 24 hours
def load_source_caps(_conn):
    cur = _conn.cursor()
    cur.execute("""
                SELECT source, bool_or(has_metadata)
                FROM theorem_search_qwen
                GROUP BY source;
                """)
    caps = {
        source: {"has_metadata": has_meta}
        for source, has_meta in cur.fetchall()
    }
    cur.close()
    return caps

@st.cache_data(ttl=60*60*24)
def load_authors(_conn):
    cur = _conn.cursor()
    cur.execute("""
        SELECT source, unnest(authors)
        FROM theorem_search_qwen
        WHERE authors IS NOT NULL;
    """)
    from collections import defaultdict
    authors = defaultdict(set)
    for source, author in cur.fetchall():
        if source and author:
            authors[source].add(author)
    cur.close()
    return {s: sorted(v) for s, v in authors.items()}

@st.cache_data(ttl=60*60*24)
def load_tags(_conn):
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

@st.cache_data(ttl=60*60*24)
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

def fetch_results(_conn, citation_weight, query_vec, params, where_sql, top_k):
    cur = _conn.cursor()
    cur.execute("SET LOCAL hnsw.ef_search = %s;", (80,))
    if citation_weight == 0.0:
        sql = f"""
            SELECT
                slogan_id,
                theorem_id,
                paper_id,
                citations,
                has_metadata,
                theorem_type,
                title,
                authors,
                link,
                year,
                primary_category,
                categories,
                source,
                theorem_name,
                theorem_body,
                theorem_slogan,
                (1.0 - (embedding <=> %s::vector)) AS similarity
            FROM theorem_search_qwen
            {where_sql}
            ORDER BY embedding <=> %s::vector
            LIMIT %s;
            """

        exec_params = [
            query_vec,
            *params,
            query_vec,
            top_k,
        ]

        cur.execute(sql, exec_params)
        rows = cur.fetchall()
        results = [
            {
                **row_to_dict(cur, row),
                "similarity": row[-1],
                "score": row[-1],
            }
            for row in rows
        ]
    else:
        sql = f"""
            WITH ann AS MATERIALIZED (
                SELECT
                    slogan_id,
                    theorem_id,
                    paper_id,
                    citations,
                    has_metadata,
                    theorem_type,
                    title,
                    authors,
                    link,
                    year,
                    primary_category,
                    categories,
                    source,
                    theorem_name,
                    theorem_body,
                    theorem_slogan,
                    (1.0 - (embedding <=> %s::vector)) AS similarity
                FROM theorem_search_qwen
                {where_sql}
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            )
            SELECT *,
                   (
                       similarity +
                       %s * CASE
                              WHEN citations IS NOT NULL AND citations > 0
                              THEN ln(citations::float)
                              ELSE 0
                            END
                   ) AS score
            FROM ann
            ORDER BY score DESC, similarity DESC
            LIMIT %s;
            """

        exec_params = [
            query_vec,
            *params,
            query_vec,
            min(5 * top_k, 200),
            citation_weight,
            top_k,
        ]

        cur.execute(sql, exec_params)
        rows = cur.fetchall()
        results = [
            {
                **row_to_dict(cur, row),
                "similarity": row[-2],
                "score": row[-1],
            }
            for row in rows
        ]

        cur.close()

    return results