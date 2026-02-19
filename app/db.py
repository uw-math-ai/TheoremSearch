import streamlit as st
import json
import os
import boto3
import psycopg2
from contextlib import contextmanager
from pgvector.psycopg2 import register_vector
from dotenv import load_dotenv
from utils import json_safe
from openai import OpenAI
from psycopg2.pool import SimpleConnectionPool

load_dotenv()

_openai_client = OpenAI(
    base_url="https://api.tokenfactory.nebius.com/v1/",
    api_key=os.environ.get("NEBIUS_API_KEY"),
)

_region = os.getenv("AWS_REGION")
_secret_arn = os.getenv("RDS_SECRET_ARN")
_dbname = os.getenv("RDS_DB_NAME")
_sm_client = boto3.client("secretsmanager", region_name=_region)
_secret_value = _sm_client.get_secret_value(SecretId=_secret_arn)
_secret_dict = json.loads(_secret_value["SecretString"])

_reader_host = os.getenv("RDS_READER_HOST")
_writer_host = os.getenv("RDS_WRITER_HOST")

_reader_pool = SimpleConnectionPool(
    1, 10,
    host=_reader_host,
    port=int(_secret_dict.get("port", 5432)),
    dbname=_dbname or _secret_dict.get("dbname"),
    user=_secret_dict["username"],
    password=_secret_dict["password"],
    sslmode="require",
)

_writer_pool = SimpleConnectionPool(
    1, 5,
    host=_writer_host,
    port=int(_secret_dict.get("port", 5432)),
    dbname=_dbname or _secret_dict.get("dbname"),
    user=_secret_dict["username"],
    password=_secret_dict["password"],
    sslmode="require",
)

def embed_query(query: str):
    response = _openai_client.embeddings.create(
        model="Qwen/Qwen3-Embedding-8B",
        input=query
    )
    return response.data[0].embedding

@st.cache_data(ttl=60*60*24*7)
def cached_embed(query):
    return embed_query(query)

@contextmanager
def get_rds_conn(host: str):
    with psycopg2.connect(
        host=host,
        port=int(_secret_dict.get("port", 5432)),
        dbname=_dbname or _secret_dict.get("dbname"),
        user=_secret_dict["username"],
        password=_secret_dict["password"],
        sslmode="require",
    ) as conn:
        register_vector(conn)
        yield conn

@contextmanager
def reader_conn():
    conn = _reader_pool.getconn()
    try:
        register_vector(conn)
        yield conn
    finally:
        _reader_pool.putconn(conn)

@contextmanager
def writer_conn():
    conn = _writer_pool.getconn()
    try:
        register_vector(conn)
        yield conn
    finally:
        _writer_pool.putconn(conn)

@st.cache_data(ttl=60*60*24*7)
def load_sources():
    with reader_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT sources FROM mv_sources;")
        return cur.fetchone()[0] or []

@st.cache_data(ttl=60*60*24*7)
def load_source_caps():
    with reader_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT source, has_metadata FROM mv_source_caps;")
        return {row[0]: {"has_metadata": row[1]} for row in cur.fetchall()}

@st.cache_data(ttl=60*60*24*7)
def load_authors():
    with reader_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT source, authors FROM mv_authors_by_source;")
        return {row[0]: row[1] for row in cur.fetchall()}

@st.cache_data(ttl=60*60*24*7)
def load_tags():
    with reader_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT source, tags FROM mv_tags_by_source;")
        return {row[0]: row[1] for row in cur.fetchall()}

@st.cache_data(ttl=60*60*24*7)
def load_theorem_count():
    with reader_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT cnt FROM mv_theorem_count;")
        return cur.fetchone()[0]

def row_to_dict(cursor, row):
    return {desc[0]: row[i] for i, desc in enumerate(cursor.description)}

def insert_feedback(payload: dict):
    with writer_conn() as conn:
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

def insert_query(query: str, filters: dict):
    with writer_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.queries (query, sources, filters)
                VALUES (%s, %s, %s);
                """,
                (
                    query,
                    filters["sources"],
                    json.dumps(json_safe(filters)),
                ),
            )

def fetch_candidate_ids(
    query_vec,
    citation_weight,
    top_k,
    selected_sources,
    filter_clauses,
    filter_params,
):
    if not selected_sources:
        return []

    extra_where = ""
    if filter_clauses:
        extra_where = " AND " + " AND ".join(filter_clauses)

    with reader_conn() as conn, conn.cursor() as cur:
        # Tune these
        per_source_multiplier = 3
        ef_search = max(80, top_k * 4)

        cur.execute("SET LOCAL hnsw.ef_search = %s;", (ef_search,))
        cur.execute("SET LOCAL hnsw.iterative_scan = 'relaxed_order';")

        all_rows = []

        for source in selected_sources:
            sql = f"""
            WITH ann AS (
                SELECT
                    slogan_id,
                    citations,
                    embedding
                FROM theorem_search_qwen8b
                WHERE source = %(source)s{extra_where}
                ORDER BY
                    (binary_quantize(embedding)::bit(4096))
                    <~>
                    binary_quantize(%(query_vec_ann)s::vector(4096))::bit(4096)
                LIMIT %(per_source_limit)s
            )
            SELECT
                slogan_id,
                (1.0 - (embedding <=> %(query_vec_rerank)s::vector(4096))) AS similarity,
                (1.0 - (embedding <=> %(query_vec_rerank)s::vector(4096)))
                + %(citation_weight)s * CASE
                    WHEN citations > 0 THEN ln(citations::float)
                    ELSE 0
                  END AS score
            FROM ann;
            """

            params = {
                "source": source,
                "query_vec_ann": query_vec,
                "query_vec_rerank": query_vec,
                "citation_weight": citation_weight,
                "per_source_limit": top_k * per_source_multiplier,
                **filter_params,
            }

            cur.execute(sql, params)
            all_rows.extend(cur.fetchall())

        if not all_rows:
            return []

        # Global rerank across sources
        all_rows.sort(key=lambda x: x[2], reverse=True)

        return all_rows[:top_k]

def fetch_full_rows(slogan_rows):
    if not slogan_rows:
        return []

    slogan_ids = [r[0] for r in slogan_rows]
    score_map = {r[0]: (r[1], r[2]) for r in slogan_rows}

    with reader_conn() as conn, conn.cursor() as cur:
        sql = """
        SELECT
            slogan_id,
            theorem_id,
            paper_id,
            theorem_name,
            theorem_body,
            theorem_slogan,
            theorem_type,
            title,
            authors,
            link,
            year,
            journal_published,
            primary_category,
            categories,
            citations,
            source,
            has_metadata
        FROM theorem_search_qwen8b
        WHERE slogan_id = ANY(%(ids)s)
        ORDER BY array_position(%(ids)s, slogan_id);
        """

        cur.execute(sql, {"ids": slogan_ids})
        rows = cur.fetchall()

    return [
        {
            **row_to_dict(cur, row),
            "similarity": score_map[row[0]][0],
            "score": score_map[row[0]][1],
        }
        for row in rows
    ]

def fetch_results(
    query_vec,
    citation_weight,
    top_k,
    selected_sources,
    filter_clauses,
    filter_params,
):
    candidates = fetch_candidate_ids(
        query_vec=query_vec,
        citation_weight=citation_weight,
        top_k=top_k,
        selected_sources=selected_sources,
        filter_clauses=filter_clauses,
        filter_params=filter_params,
    )

    return fetch_full_rows(candidates)
