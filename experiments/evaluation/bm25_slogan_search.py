from __future__ import annotations

import argparse
import json
import math
import os
import re
import textwrap
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable

import boto3
import psycopg2
from dotenv import load_dotenv

load_dotenv()

TOKEN_RE = re.compile(r"\w+(?:[-./^]\w+)*", re.UNICODE)
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_ident(value: str, label: str) -> str:
    if not IDENT_RE.fullmatch(value):
        raise ValueError(f"Invalid SQL identifier for {label}: {value!r}")
    return value


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


_SECRET_CACHE: dict | None = None


def load_rds_secret() -> dict:
    global _SECRET_CACHE
    if _SECRET_CACHE is None:
        region = require_env("AWS_REGION")
        secret_arn = require_env("RDS_SECRET_ARN")
        client = boto3.client("secretsmanager", region_name=region)
        response = client.get_secret_value(SecretId=secret_arn)
        _SECRET_CACHE = json.loads(response["SecretString"])
    return _SECRET_CACHE


def pg_connect():
    secret = load_rds_secret()

    host = os.getenv("RDS_HOST") or secret.get("host")
    if not host:
        raise RuntimeError("Missing database host. Set RDS_HOST or store host in the RDS secret.")

    dbname = (
        os.getenv("RDS_DB_NAME")
        or os.getenv("RDS_DBNAME")
        or secret.get("dbname")
        or "postgres"
    )
    port = int(os.getenv("RDS_PORT") or secret.get("port", 5432))
    user = secret.get("username", "postgres")
    password = secret["password"]

    return psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
        sslmode="require",
    )


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall((text or "").lower())


@dataclass(frozen=True)
class SearchResult:
    rank: int
    slogan_id: int
    score: float
    slogan: str


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.slogan_ids: list[int] = []
        self.slogans: list[str] = []
        self.doc_lengths: list[int] = []
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.doc_freqs: Counter[str] = Counter()
        self.idf: dict[str, float] = {}
        self.avgdl = 0.0

    @property
    def corpus_size(self) -> int:
        return len(self.slogan_ids)

    def add_document(self, slogan_id: int, slogan: str) -> None:
        tokens = tokenize(slogan)
        if not tokens:
            return

        doc_index = len(self.slogan_ids)
        self.slogan_ids.append(int(slogan_id))
        self.slogans.append(slogan)
        self.doc_lengths.append(len(tokens))

        counts = Counter(tokens)
        for term, freq in counts.items():
            self.doc_freqs[term] += 1
            self.postings[term].append((doc_index, freq))

    def finalize(self) -> None:
        if not self.slogan_ids:
            raise RuntimeError("No documents were loaded into the BM25 index.")

        self.avgdl = sum(self.doc_lengths) / self.corpus_size
        self.idf = {
            term: math.log1p((self.corpus_size - df + 0.5) / (df + 0.5))
            for term, df in self.doc_freqs.items()
        }

    def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        scores: dict[int, float] = defaultdict(float)

        for term in query_tokens:
            postings = self.postings.get(term)
            if not postings:
                continue

            term_idf = self.idf[term]
            for doc_index, term_freq in postings:
                doc_len = self.doc_lengths[doc_index]
                denom = term_freq + self.k1 * (1 - self.b + self.b * doc_len / self.avgdl)
                scores[doc_index] += term_idf * (term_freq * (self.k1 + 1)) / denom

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top_k]
        return [
            SearchResult(
                rank=rank,
                slogan_id=self.slogan_ids[doc_index],
                score=score,
                slogan=self.slogans[doc_index],
            )
            for rank, (doc_index, score) in enumerate(ranked, start=1)
        ]


def iter_slogans(
    conn,
    embedding_table: str,
    slogan_table: str,
    slogan_id_col: str,
    slogan_text_col: str,
    batch_size: int,
    limit: int | None,
) -> Iterable[tuple[int, str]]:
    embedding_table = validate_ident(embedding_table, "embedding_table")
    slogan_table = validate_ident(slogan_table, "slogan_table")
    slogan_id_col = validate_ident(slogan_id_col, "slogan_id_col")
    slogan_text_col = validate_ident(slogan_text_col, "slogan_text_col")

    sql = f"""
        SELECT DISTINCT s.{slogan_id_col}, s.{slogan_text_col}
        FROM {embedding_table} AS e
        INNER JOIN {slogan_table} AS s
            ON s.{slogan_id_col} = e.{slogan_id_col}
        WHERE s.{slogan_text_col} IS NOT NULL
          AND btrim(s.{slogan_text_col}) <> ''
        ORDER BY s.{slogan_id_col}
    """

    params: tuple[int, ...] = ()
    if limit is not None:
        sql += "\nLIMIT %s"
        params = (limit,)

    with conn.cursor(name="bm25_slogan_cursor") as cur:
        cur.itersize = batch_size
        cur.execute(sql, params)

        while True:
            rows = cur.fetchmany(batch_size)
            if not rows:
                break
            for slogan_id, slogan in rows:
                yield int(slogan_id), slogan


def build_index(args: argparse.Namespace) -> BM25Index:
    started_at = time.time()
    index = BM25Index(k1=args.k1, b=args.b)

    with pg_connect() as conn:
        loaded = 0
        for slogan_id, slogan in iter_slogans(
            conn=conn,
            embedding_table=args.embedding_table,
            slogan_table=args.slogan_table,
            slogan_id_col=args.slogan_id_col,
            slogan_text_col=args.slogan_text_col,
            batch_size=args.batch_size,
            limit=args.limit,
        ):
            index.add_document(slogan_id, slogan)
            loaded += 1
            if loaded % 10000 == 0:
                print(f"Loaded {loaded:,} slogans into the BM25 index...")

    index.finalize()
    elapsed = time.time() - started_at
    print(
        f"Built BM25 index over {index.corpus_size:,} slogans "
        f"in {elapsed:.2f}s (avgdl={index.avgdl:.2f})."
    )
    return index


def print_results(results: list[SearchResult]) -> None:
    if not results:
        print("No BM25 matches found.")
        return

    for result in results:
        wrapped = textwrap.fill(
            result.slogan,
            width=100,
            initial_indent="    ",
            subsequent_indent="    ",
        )
        print(f"[{result.rank}] slogan_id={result.slogan_id} score={result.score:.6f}")
        print(wrapped)
        print()


def run_query(index: BM25Index, query: str, top_k: int, as_json: bool) -> None:
    results = index.search(query, top_k=top_k)
    if as_json:
        payload = {
            "query": query,
            "top_k": top_k,
            "results": [
                {
                    "rank": result.rank,
                    "slogan_id": result.slogan_id,
                    "score": result.score,
                    "slogan": result.slogan,
                }
                for result in results
            ],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    print_results(results)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a BM25 index over theorem slogans joined from "
            "theorem_embedding_qwen8b and theorem_slogan."
        )
    )
    parser.add_argument(
        "-q",
        "--query",
        help="Query to run. If omitted, the script enters interactive mode.",
    )
    parser.add_argument(
        "-k",
        "--top-k",
        type=int,
        default=10,
        help="How many BM25 matches to return per query.",
    )
    parser.add_argument(
        "--embedding-table",
        default="theorem_embedding_qwen8b",
        help="Embedding table containing slogan_id values.",
    )
    parser.add_argument(
        "--slogan-table",
        default="theorem_slogan",
        help="Table containing the slogan text.",
    )
    parser.add_argument(
        "--slogan-id-col",
        default="slogan_id",
        help="Join key shared by the embedding and slogan tables.",
    )
    parser.add_argument(
        "--slogan-text-col",
        default="slogan",
        help="Text column to run BM25 over.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5000,
        help="How many rows to stream from Postgres at a time while building the index.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap on how many slogans to load, useful for quick debugging.",
    )
    parser.add_argument(
        "--k1",
        type=float,
        default=1.5,
        help="BM25 k1 parameter.",
    )
    parser.add_argument(
        "--b",
        type=float,
        default=0.75,
        help="BM25 b parameter.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print results as JSON.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    index = build_index(args)

    if args.query:
        run_query(index, args.query, top_k=args.top_k, as_json=args.json)
        return

    print("Interactive BM25 mode. Press Enter on an empty line to exit.")
    while True:
        query = input("Query> ").strip()
        if not query:
            break
        run_query(index, query, top_k=args.top_k, as_json=args.json)


if __name__ == "__main__":
    main()
