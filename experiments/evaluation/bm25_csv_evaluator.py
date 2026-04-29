from __future__ import annotations

import csv
import math
import re
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from bm25_slogan_search import pg_connect, validate_ident

TOKEN_RE = re.compile(r"\w+(?:[-./^]\w+)*", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall((text or "").lower())


@dataclass(frozen=True)
class SearchResult:
    rank: int
    slogan_id: int
    score: float


@dataclass(frozen=True)
class RankedTheoremResult:
    rank: int
    slogan_id: int
    theorem_id: int
    paper_id: str
    theorem_name: str
    score: float
    slogan: str


@dataclass(frozen=True)
class EvalQuery:
    query: str
    paper_id: str
    name: str
    target_theorem_id: int | None


@dataclass(frozen=True)
class BM25EvalConfig:
    csv_path: str
    theorem_table: str = "theorem"
    slogan_table: str = "theorem_slogan"
    slogan_id_col: str = "slogan_id"
    slogan_text_col: str = "slogan"
    theorem_id_col: str = "theorem_id"
    theorem_name_col: str = "name"
    theorem_paper_id_col: str = "paper_id"
    batch_size: int = 5000
    limit: int | None = None
    k1: float = 1.5
    b: float = 0.75
    raw_top_k: int = 200
    eval_top_k: int = 20


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.slogan_ids: list[int] = []
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
        self.doc_lengths.append(len(tokens))

        counts = Counter(tokens)
        for term, freq in counts.items():
            self.doc_freqs[term] += 1
            self.postings[term].append((doc_index, freq))

    def finalize(self) -> None:
        if not self.slogan_ids:
            raise RuntimeError("No slogans were loaded into the BM25 index.")

        self.avgdl = sum(self.doc_lengths) / self.corpus_size
        self.idf = {
            term: math.log1p((self.corpus_size - df + 0.5) / (df + 0.5))
            for term, df in self.doc_freqs.items()
        }

    def search(self, query: str, top_k: int) -> list[SearchResult]:
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
            )
            for rank, (doc_index, score) in enumerate(ranked, start=1)
        ]


def _validate_config(config: BM25EvalConfig) -> None:
    if config.eval_top_k < 20:
        raise ValueError("eval_top_k must be at least 20 to compute Hit@20 and MRR@20.")
    if config.raw_top_k < config.eval_top_k:
        raise ValueError("raw_top_k must be >= eval_top_k.")
    if config.batch_size <= 0:
        raise ValueError("batch_size must be positive.")
    if config.limit is not None and config.limit <= 0:
        raise ValueError("limit must be positive when provided.")


def iter_slogans(
    conn,
    slogan_table: str,
    slogan_id_col: str,
    slogan_text_col: str,
    batch_size: int,
    limit: int | None,
):
    slogan_table = validate_ident(slogan_table, "slogan_table")
    slogan_id_col = validate_ident(slogan_id_col, "slogan_id_col")
    slogan_text_col = validate_ident(slogan_text_col, "slogan_text_col")

    sql = f"""
        SELECT {slogan_id_col}, {slogan_text_col}
        FROM {slogan_table}
        WHERE {slogan_text_col} IS NOT NULL
          AND btrim({slogan_text_col}) <> ''
        ORDER BY {slogan_id_col}
    """
    params: tuple[int, ...] = ()
    if limit is not None:
        sql += "\nLIMIT %s"
        params = (limit,)

    with conn.cursor(name="bm25_eval_slogan_cursor") as cur:
        cur.itersize = batch_size
        cur.execute(sql, params)

        while True:
            rows = cur.fetchmany(batch_size)
            if not rows:
                break
            for slogan_id, slogan in rows:
                yield int(slogan_id), slogan


def build_index(config: BM25EvalConfig) -> BM25Index:
    started_at = time.time()
    index = BM25Index(k1=config.k1, b=config.b)

    with pg_connect() as conn:
        loaded = 0
        for slogan_id, slogan in iter_slogans(
            conn=conn,
            slogan_table=config.slogan_table,
            slogan_id_col=config.slogan_id_col,
            slogan_text_col=config.slogan_text_col,
            batch_size=config.batch_size,
            limit=config.limit,
        ):
            index.add_document(slogan_id, slogan)
            loaded += 1
            if loaded % 100000 == 0:
                print(f"Loaded {loaded:,} slogans...")

    index.finalize()
    elapsed = time.time() - started_at
    print(
        f"Built BM25 index over {index.corpus_size:,} slogans "
        f"in {elapsed:.2f}s (avgdl={index.avgdl:.2f})."
    )
    return index


def _read_csv_rows(csv_path: str) -> list[dict[str, str]]:
    path = Path(csv_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or [])
        required = {"query", "paper_id", "name"}
        missing = required - fieldnames
        if missing:
            raise ValueError(
                f"CSV is missing required columns: {sorted(missing)}. "
                f"Found columns: {sorted(fieldnames)}"
            )

        rows: list[dict[str, str]] = []
        for line_number, row in enumerate(reader, start=2):
            query = (row.get("query") or "").strip()
            paper_id = (row.get("paper_id") or "").strip()
            name = (row.get("name") or "").strip()
            if not query or not paper_id or not name:
                raise ValueError(
                    f"CSV row {line_number} must have non-empty query, paper_id, and name values."
                )
            rows.append({"query": query, "paper_id": paper_id, "name": name})

    if not rows:
        raise RuntimeError(f"CSV file contains no evaluation rows: {path}")
    return rows


def resolve_target_theorem_ids(
    conn,
    config: BM25EvalConfig,
    rows: Sequence[dict[str, str]],
) -> list[EvalQuery]:
    theorem_table = validate_ident(config.theorem_table, "theorem_table")
    theorem_id_col = validate_ident(config.theorem_id_col, "theorem_id_col")
    theorem_name_col = validate_ident(config.theorem_name_col, "theorem_name_col")
    theorem_paper_id_col = validate_ident(config.theorem_paper_id_col, "theorem_paper_id_col")

    unique_pairs = sorted({(row["paper_id"], row["name"]) for row in rows})
    placeholders = ", ".join(["(%s, %s)"] * len(unique_pairs))
    sql = f"""
        SELECT {theorem_id_col}, {theorem_paper_id_col}, {theorem_name_col}
        FROM {theorem_table}
        WHERE ({theorem_paper_id_col}, {theorem_name_col}) IN ({placeholders})
    """
    params = [value for pair in unique_pairs for value in pair]

    with conn.cursor() as cur:
        cur.execute(sql, params)
        resolved = {
            (paper_id, name): int(theorem_id)
            for theorem_id, paper_id, name in cur.fetchall()
        }

    return [
        EvalQuery(
            query=row["query"],
            paper_id=row["paper_id"],
            name=row["name"],
            target_theorem_id=resolved.get((row["paper_id"], row["name"])),
        )
        for row in rows
    ]


def fetch_ranked_metadata(
    conn,
    config: BM25EvalConfig,
    slogan_ids: Sequence[int],
) -> dict[int, tuple[int, str, str, str]]:
    if not slogan_ids:
        return {}

    slogan_table = validate_ident(config.slogan_table, "slogan_table")
    slogan_id_col = validate_ident(config.slogan_id_col, "slogan_id_col")
    slogan_text_col = validate_ident(config.slogan_text_col, "slogan_text_col")
    theorem_table = validate_ident(config.theorem_table, "theorem_table")
    theorem_id_col = validate_ident(config.theorem_id_col, "theorem_id_col")
    theorem_name_col = validate_ident(config.theorem_name_col, "theorem_name_col")
    theorem_paper_id_col = validate_ident(config.theorem_paper_id_col, "theorem_paper_id_col")

    sql = f"""
        SELECT
            s.{slogan_id_col},
            t.{theorem_id_col},
            t.{theorem_paper_id_col},
            t.{theorem_name_col},
            s.{slogan_text_col}
        FROM {slogan_table} AS s
        INNER JOIN {theorem_table} AS t
            ON t.{theorem_id_col} = s.{theorem_id_col}
        WHERE s.{slogan_id_col} = ANY(%s)
    """

    with conn.cursor() as cur:
        cur.execute(sql, (list(slogan_ids),))
        return {
            int(slogan_id): (int(theorem_id), paper_id, theorem_name, slogan)
            for slogan_id, theorem_id, paper_id, theorem_name, slogan in cur.fetchall()
        }


def rank_theorem_results(
    index: BM25Index,
    conn,
    config: BM25EvalConfig,
    query: str,
) -> list[RankedTheoremResult]:
    raw_results = index.search(query, top_k=config.raw_top_k)
    metadata = fetch_ranked_metadata(conn, config, [result.slogan_id for result in raw_results])

    ranked: list[RankedTheoremResult] = []
    seen_theorem_ids: set[int] = set()
    for result in raw_results:
        meta = metadata.get(result.slogan_id)
        if meta is None:
            continue

        theorem_id, paper_id, theorem_name, slogan = meta
        if theorem_id in seen_theorem_ids:
            continue

        seen_theorem_ids.add(theorem_id)
        ranked.append(
            RankedTheoremResult(
                rank=len(ranked) + 1,
                slogan_id=result.slogan_id,
                theorem_id=theorem_id,
                paper_id=paper_id,
                theorem_name=theorem_name,
                score=result.score,
                slogan=slogan,
            )
        )
        if len(ranked) >= config.eval_top_k:
            break

    return ranked


def _match_rank(
    target_theorem_id: int | None,
    ranked_results: Sequence[RankedTheoremResult],
) -> int | None:
    if target_theorem_id is None:
        return None
    for result in ranked_results:
        if result.theorem_id == target_theorem_id:
            return result.rank
    return None


def _compute_metrics(per_query: Sequence[dict]) -> dict[str, float]:
    num_queries = len(per_query)
    if num_queries == 0:
        raise RuntimeError("Cannot compute metrics for an empty evaluation set.")

    def mean(key: str) -> float:
        return sum(float(row[key]) for row in per_query) / num_queries

    return {
        "Hit@1": mean("hit@1"),
        "Hit@10": mean("hit@10"),
        "Hit@20": mean("hit@20"),
        "MRR@20": mean("mrr@20"),
    }


def run_bm25_csv_evaluation(config: BM25EvalConfig) -> dict:
    _validate_config(config)
    started_at = time.time()

    index = build_index(config)

    with pg_connect() as conn:
        eval_queries = resolve_target_theorem_ids(conn, config, _read_csv_rows(config.csv_path))
        per_query: list[dict] = []

        for idx, eval_query in enumerate(eval_queries, start=1):
            ranked_results = rank_theorem_results(index, conn, config, eval_query.query)
            match_rank = _match_rank(eval_query.target_theorem_id, ranked_results)
            resolved_target = eval_query.target_theorem_id is not None
            match_position = match_rank if match_rank is not None else "miss"

            print(f"[{idx}/{len(eval_queries)}] match position: {match_position}")

            per_query.append(
                {
                    "query": eval_query.query,
                    "paper_id": eval_query.paper_id,
                    "name": eval_query.name,
                    "target_theorem_id": eval_query.target_theorem_id,
                    "target_resolved": resolved_target,
                    "match_rank": match_rank,
                    "hit@1": 1.0 if match_rank is not None and match_rank <= 1 else 0.0,
                    "hit@10": 1.0 if match_rank is not None and match_rank <= 10 else 0.0,
                    "hit@20": 1.0 if match_rank is not None and match_rank <= 20 else 0.0,
                    "mrr@20": (1.0 / match_rank) if match_rank is not None and match_rank <= 20 else 0.0,
                    "top_results": [asdict(result) for result in ranked_results],
                }
            )

            if idx % 10 == 0 or idx == len(eval_queries):
                print(f"Evaluated {idx}/{len(eval_queries)} queries...")

    metrics = _compute_metrics(per_query)
    elapsed = time.time() - started_at

    return {
        "config": asdict(config),
        "num_queries": len(per_query),
        "num_unresolved_targets": sum(not row["target_resolved"] for row in per_query),
        "index_corpus_size": index.corpus_size,
        "elapsed_seconds": elapsed,
        "metrics": metrics,
        "per_query": per_query,
    }


def print_evaluation_report(evaluation: dict, max_examples: int = 5) -> None:
    print(f"Queries evaluated: {evaluation['num_queries']}")
    print(f"Unresolved targets: {evaluation['num_unresolved_targets']}")
    print(f"Index size: {evaluation['index_corpus_size']:,} slogans")
    print(f"Elapsed: {evaluation['elapsed_seconds']:.2f}s")

    for metric_name in ("Hit@1", "Hit@10", "Hit@20", "MRR@20"):
        print(f"{metric_name:<7}: {evaluation['metrics'][metric_name]:.4f}")

    misses = [row for row in evaluation["per_query"] if row["match_rank"] is None][:max_examples]
    if not misses:
        return

    print("")
    print("Sample misses:")
    for row in misses:
        print(f"Query: {row['query']}")
        print(f"Expected: {row['paper_id']} | {row['name']}")
        if not row["target_resolved"]:
            print("Target resolution: could not match this CSV row to theorem.theorem_id")
        if row["top_results"]:
            top = row["top_results"][0]
            print(
                "Top-1: "
                f"{top['paper_id']} | {top['theorem_name']} "
                f"(score={top['score']:.4f})"
            )
        else:
            print("Top-1: no result")
        print("")
