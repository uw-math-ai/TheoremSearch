from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Sequence
import os

import requests

from bm25_csv_evaluator import BM25EvalConfig, _read_csv_rows, build_index, rank_theorem_results
from bm25_slogan_search import pg_connect, validate_ident

WHITESPACE_RE = re.compile(r"\s+")
PUNCT_TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u00a0": " ",
    }
)


def normalize_match_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.translate(PUNCT_TRANSLATION)
    text = WHITESPACE_RE.sub(" ", text).strip()
    return text.casefold()


def theorem_key(paper_id: str, theorem_name: str) -> tuple[str, str]:
    return ((paper_id or "").strip(), normalize_match_text(theorem_name))


@dataclass(frozen=True, slots=True)
class DenseSearchResult:
    rank: int
    paper_id: str
    theorem_name: str
    score: float | None = None


@dataclass(frozen=True, slots=True)
class RRFFusedResult:
    rank: int
    paper_id: str
    theorem_name: str
    rrf_score: float
    bm25_rank: int | None
    dense_rank: int | None


@dataclass(frozen=True, slots=True)
class RRFExperimentConfig:
    csv_path: str
    bm25_config: BM25EvalConfig
    dense_search_url: str = "https://api.theoremsearch.com/search"
    dense_n_results: int = 200
    dense_min_n_results: int = 20
    inter_query_delay_seconds: float = 0.0
    rrf_k: int = 60
    eval_top_k: int = 20
    timeout_seconds: float = 60.0
    dense_max_retries: int = 2
    dense_retry_backoff_seconds: float = 1.0
    continue_on_dense_error: bool = True
    local_dense_table: str = "raw_theorem_embedding_gemma"
    local_dense_join_col: str = "theorem_id"
    local_dense_vector_col: str = "embedding"
    local_dense_metric: str = "cosine"
    local_embedding_model_name: str = "google/embeddinggemma-300m"
    local_embedding_prompt: str = (
        "Instruct: Given a math search query, retrieve theorems mathematically "
        "equivalent to the query.\nQuery:"
    )
    local_embedding_device: str = "cpu"


def _validate_config(config: RRFExperimentConfig) -> None:
    if config.dense_n_results <= 0:
        raise ValueError("dense_n_results must be positive.")
    if config.dense_min_n_results <= 0:
        raise ValueError("dense_min_n_results must be positive.")
    if config.rrf_k < 0:
        raise ValueError("rrf_k must be non-negative.")
    if config.eval_top_k <= 0:
        raise ValueError("eval_top_k must be positive.")
    if config.timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive.")
    if config.inter_query_delay_seconds < 0:
        raise ValueError("inter_query_delay_seconds must be non-negative.")
    if config.dense_max_retries < 0:
        raise ValueError("dense_max_retries must be non-negative.")
    if config.dense_retry_backoff_seconds < 0:
        raise ValueError("dense_retry_backoff_seconds must be non-negative.")


def _validate_local_dense_config(config: RRFExperimentConfig) -> None:
    validate_ident(config.local_dense_table, "local_dense_table")
    validate_ident(config.local_dense_join_col, "local_dense_join_col")
    validate_ident(config.local_dense_vector_col, "local_dense_vector_col")
    if config.local_dense_metric not in {"cosine", "ip", "l2"}:
        raise ValueError("local_dense_metric must be one of: cosine, ip, l2.")
    if not (config.local_embedding_model_name or "").strip():
        raise ValueError("local_embedding_model_name must be non-empty.")
    if not (config.local_embedding_device or "").strip():
        raise ValueError("local_embedding_device must be non-empty.")


def _dense_n_results_schedule(config: RRFExperimentConfig) -> list[int]:
    minimum = min(config.dense_n_results, config.dense_min_n_results)
    current = config.dense_n_results
    schedule: list[int] = []

    while True:
        if current not in schedule:
            schedule.append(current)
        if current <= minimum:
            break
        next_n = max(minimum, current // 2)
        if next_n == current:
            break
        current = next_n

    return schedule


def _extract_path(payload: Any, path: Sequence[str]) -> Any:
    cur = payload
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def _first_present(payload: dict, paths: Sequence[Sequence[str]]) -> Any:
    for path in paths:
        value = _extract_path(payload, path)
        if value not in (None, ""):
            return value
    return None


def _coerce_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dense_items_from_payload(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        for key in ("results", "data", "matches", "items", "documents", "theorems"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

        for key, value in payload.items():
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

        if "paper_id" in payload or "name" in payload or "theorem_name" in payload:
            return [payload]

        keys_preview = ", ".join(sorted(payload.keys())[:10])
        raise ValueError(f"Unsupported dense-search response shape. Top-level keys: {keys_preview}")

    raise ValueError(f"Unsupported dense-search response type: {type(payload).__name__}")


def _fetch_theorem_pairs_by_id(conn, theorem_ids: Sequence[int], theorem_table: str) -> dict[int, tuple[str, str]]:
    if not theorem_ids:
        return {}

    theorem_table = validate_ident(theorem_table, "theorem_table")
    sql = f"""
        SELECT theorem_id, paper_id, name
        FROM {theorem_table}
        WHERE theorem_id = ANY(%s)
    """

    with conn.cursor() as cur:
        cur.execute(sql, (list(theorem_ids),))
        return {
            int(theorem_id): (paper_id, name)
            for theorem_id, paper_id, name in cur.fetchall()
        }


def _vector_to_pgvector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(f"{float(value):.8f}" for value in vector) + "]"


def _local_dense_sql(config: RRFExperimentConfig) -> str:
    theorem_table = validate_ident(config.bm25_config.theorem_table, "theorem_table")
    theorem_id_col = validate_ident(config.bm25_config.theorem_id_col, "theorem_id_col")
    theorem_name_col = validate_ident(config.bm25_config.theorem_name_col, "theorem_name_col")
    theorem_paper_id_col = validate_ident(config.bm25_config.theorem_paper_id_col, "theorem_paper_id_col")
    emb_table = validate_ident(config.local_dense_table, "local_dense_table")
    emb_join_col = validate_ident(config.local_dense_join_col, "local_dense_join_col")
    emb_vector_col = validate_ident(config.local_dense_vector_col, "local_dense_vector_col")

    if config.local_dense_metric == "cosine":
        op = "<=>"
        score_expr = f"(1 - (e.{emb_vector_col} {op} %s::vector))"
        order_expr = f"(e.{emb_vector_col} {op} %s::vector) ASC"
    elif config.local_dense_metric == "ip":
        op = "<#>"
        score_expr = f"(-1 * (e.{emb_vector_col} {op} %s::vector))"
        order_expr = f"(e.{emb_vector_col} {op} %s::vector) ASC"
    else:
        op = "<->"
        score_expr = f"(-1 * (e.{emb_vector_col} {op} %s::vector))"
        order_expr = f"(e.{emb_vector_col} {op} %s::vector) ASC"

    return f"""
        SELECT
            t.{theorem_id_col},
            t.{theorem_paper_id_col},
            t.{theorem_name_col},
            {score_expr} AS score
        FROM {emb_table} AS e
        INNER JOIN {theorem_table} AS t
            ON e.{emb_join_col} = t.{theorem_id_col}
        ORDER BY {order_expr}
        LIMIT %s
    """


def _load_local_embedding_model(config: RRFExperimentConfig):
    from sentence_transformers import SentenceTransformer

    print(
        f"Loading local dense model {config.local_embedding_model_name!r} "
        f"on {config.local_embedding_device!r}..."
    )
    return SentenceTransformer(
        config.local_embedding_model_name,
        trust_remote_code=True,
        token=os.environ["HF_TOKEN"],
        device=config.local_embedding_device,
    )


def _encode_local_query(model, config: RRFExperimentConfig, query: str) -> list[float]:
    encoded = model.encode(
        [unicodedata.normalize("NFKC", query or "").strip()],
        convert_to_tensor=True,
        prompt=config.local_embedding_prompt,
    )
    if hasattr(encoded, "detach"):
        encoded = encoded.detach()
    if hasattr(encoded, "cpu"):
        encoded = encoded.cpu()
    if hasattr(encoded, "tolist"):
        encoded = encoded.tolist()
    if isinstance(encoded, list) and encoded and isinstance(encoded[0], list):
        encoded = encoded[0]
    if not isinstance(encoded, list) or not encoded:
        raise RuntimeError("Local dense encoder returned an unexpected embedding shape.")
    return [float(value) for value in encoded]


def fetch_local_dense_results(
    conn,
    model,
    config: RRFExperimentConfig,
    query: str,
) -> list[DenseSearchResult]:
    query_embedding = _encode_local_query(model, config, query)
    vector_literal = _vector_to_pgvector_literal(query_embedding)
    sql = _local_dense_sql(config)

    with conn.cursor() as cur:
        cur.execute(sql, (vector_literal, vector_literal, config.dense_n_results))
        rows = cur.fetchall()

    dense_results: list[DenseSearchResult] = []
    seen_theorem_ids: set[int] = set()
    for theorem_id, paper_id, theorem_name, score in rows:
        theorem_id = int(theorem_id)
        if theorem_id in seen_theorem_ids:
            continue
        seen_theorem_ids.add(theorem_id)
        dense_results.append(
            DenseSearchResult(
                rank=len(dense_results) + 1,
                paper_id=str(paper_id),
                theorem_name=str(theorem_name),
                score=_coerce_float(score),
            )
        )
        if len(dense_results) >= config.dense_n_results:
            break

    return dense_results


def fetch_dense_results(
    session: requests.Session,
    conn,
    config: RRFExperimentConfig,
    query: str,
) -> list[DenseSearchResult]:
    total_attempts = config.dense_max_retries + 1
    n_results_schedule = _dense_n_results_schedule(config)
    query_to_send = unicodedata.normalize("NFKC", query or "").strip()
    payload = None
    last_message = ""

    for n_results in n_results_schedule:
        for attempt in range(1, total_attempts + 1):
            try:
                response = session.post(
                    config.dense_search_url,
                    json={"query": query_to_send, "n_results": n_results},
                    timeout=config.timeout_seconds,
                )
                response.raise_for_status()
                payload = response.json()
                if n_results != config.dense_n_results:
                    print(
                        f"Dense search succeeded for query {query!r} with reduced "
                        f"n_results={n_results}."
                    )
                break
            except (requests.RequestException, ValueError) as exc:
                body_preview = ""
                response = getattr(exc, "response", None)
                if response is not None:
                    try:
                        text = response.text.strip()
                    except Exception:
                        text = ""
                    if text:
                        body_preview = f" | body={text[:300]!r}"

                last_message = (
                    f"Dense search failed for query {query!r} with n_results={n_results} "
                    f"after attempt {attempt}/{total_attempts}: {exc}{body_preview}"
                )

                if attempt < total_attempts:
                    print(f"{last_message}. Retrying...")
                    if config.dense_retry_backoff_seconds > 0:
                        time.sleep(config.dense_retry_backoff_seconds * attempt)
                    continue

            if payload is not None:
                break

        if payload is not None:
            break

        if n_results != n_results_schedule[-1]:
            print(
                f"Dense search is still failing for query {query!r} with n_results={n_results}. "
                "Trying a smaller candidate count..."
            )

    if payload is None:
        if config.continue_on_dense_error:
            print(f"Warning: {last_message}. Falling back to BM25-only for this query.")
            return []
        raise RuntimeError(last_message or f"Dense search failed for query {query!r}.")

    items = _dense_items_from_payload(payload)

    # Official theoremsearch API shape:
    # {
    #   "theorems": [
    #     {
    #       "theorem_id": ...,
    #       "name": ...,
    #       "paper": {"paper_id": ...},
    #       "score": ...,
    #       "similarity": ...
    #     }
    #   ]
    # }

    theorem_ids_to_resolve: list[int] = []
    parsed_items: list[dict[str, Any]] = []
    for item in items:
        theorem_id = _coerce_int(
            _first_present(
                item,
                [
                    ("theorem_id",),
                    ("theoremId",),
                    ("metadata", "theorem_id"),
                    ("metadata", "theoremId"),
                    ("result", "theorem_id"),
                    ("result", "theoremId"),
                    ("document", "theorem_id"),
                    ("document", "theoremId"),
                    ("theorem", "theorem_id"),
                    ("theorem", "theoremId"),
                ],
            )
        )
        paper_id = _first_present(
            item,
            [
                ("paper_id",),
                ("paperId",),
                ("metadata", "paper_id"),
                ("metadata", "paperId"),
                ("result", "paper_id"),
                ("result", "paperId"),
                ("document", "paper_id"),
                ("document", "paperId"),
                ("paper", "paper_id"),
                ("paper", "paperId"),
                ("source", "paper_id"),
                ("source", "paperId"),
                ("theorem", "paper_id"),
                ("theorem", "paperId"),
            ],
        )
        theorem_name = _first_present(
            item,
            [
                ("name",),
                ("theorem_name",),
                ("theoremName",),
                ("metadata", "name"),
                ("metadata", "theorem_name"),
                ("metadata", "theoremName"),
                ("result", "name"),
                ("result", "theorem_name"),
                ("result", "theoremName"),
                ("document", "name"),
                ("document", "theorem_name"),
                ("document", "theoremName"),
                ("theorem", "name"),
                ("theorem", "theorem_name"),
                ("theorem", "theoremName"),
            ],
        )
        score = _coerce_float(
            _first_present(
                item,
                [
                    ("score",),
                    ("vector_score",),
                    ("cosine_score",),
                    ("similarity",),
                    ("distance",),
                    ("metadata", "vector_score"),
                    ("metadata", "score"),
                ],
            )
        )

        if theorem_id is not None and (paper_id in (None, "") or theorem_name in (None, "")):
            theorem_ids_to_resolve.append(theorem_id)

        parsed_items.append(
            {
                "theorem_id": theorem_id,
                "paper_id": paper_id,
                "theorem_name": theorem_name,
                "score": score,
            }
        )

    theorem_pairs_by_id = _fetch_theorem_pairs_by_id(conn, theorem_ids_to_resolve, config.bm25_config.theorem_table)

    dense_results: list[DenseSearchResult] = []
    seen_keys: set[tuple[str, str]] = set()
    for item in parsed_items:
        paper_id = item["paper_id"]
        theorem_name = item["theorem_name"]
        theorem_id = item["theorem_id"]

        if (paper_id in (None, "") or theorem_name in (None, "")) and theorem_id is not None:
            resolved = theorem_pairs_by_id.get(theorem_id)
            if resolved is not None:
                paper_id, theorem_name = resolved

        if paper_id in (None, "") or theorem_name in (None, ""):
            continue

        key = theorem_key(str(paper_id), str(theorem_name))
        if key in seen_keys:
            continue

        seen_keys.add(key)
        dense_results.append(
            DenseSearchResult(
                rank=len(dense_results) + 1,
                paper_id=str(paper_id),
                theorem_name=str(theorem_name),
                score=item["score"],
            )
        )

        if len(dense_results) >= config.dense_n_results:
            break

    return dense_results


def _find_rank(results: Sequence[Any], target_key: tuple[str, str]) -> int | None:
    for result in results:
        if theorem_key(result.paper_id, result.theorem_name) == target_key:
            return result.rank
    return None


def reciprocal_rank_fusion(
    bm25_results: Sequence[Any],
    dense_results: Sequence[DenseSearchResult],
    rrf_k: int,
    top_k: int,
) -> list[RRFFusedResult]:
    fused: dict[tuple[str, str], dict[str, Any]] = {}

    for result in bm25_results:
        key = theorem_key(result.paper_id, result.theorem_name)
        entry = fused.setdefault(
            key,
            {
                "paper_id": result.paper_id,
                "theorem_name": result.theorem_name,
                "rrf_score": 0.0,
                "bm25_rank": None,
                "dense_rank": None,
            },
        )
        entry["rrf_score"] += 1.0 / (rrf_k + result.rank)
        entry["bm25_rank"] = result.rank

    for result in dense_results:
        key = theorem_key(result.paper_id, result.theorem_name)
        entry = fused.setdefault(
            key,
            {
                "paper_id": result.paper_id,
                "theorem_name": result.theorem_name,
                "rrf_score": 0.0,
                "bm25_rank": None,
                "dense_rank": None,
            },
        )
        entry["rrf_score"] += 1.0 / (rrf_k + result.rank)
        entry["dense_rank"] = result.rank

    ranked = sorted(
        fused.values(),
        key=lambda row: (
            -row["rrf_score"],
            row["bm25_rank"] if row["bm25_rank"] is not None else 10**9,
            row["dense_rank"] if row["dense_rank"] is not None else 10**9,
            row["paper_id"],
            row["theorem_name"],
        ),
    )[:top_k]

    return [
        RRFFusedResult(
            rank=rank,
            paper_id=row["paper_id"],
            theorem_name=row["theorem_name"],
            rrf_score=row["rrf_score"],
            bm25_rank=row["bm25_rank"],
            dense_rank=row["dense_rank"],
        )
        for rank, row in enumerate(ranked, start=1)
    ]


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


def run_rrf_csv_evaluation(config: RRFExperimentConfig) -> dict:
    _validate_config(config)
    started_at = time.time()

    eval_rows = _read_csv_rows(config.csv_path)
    bm25_index = build_index(config.bm25_config)

    per_query: list[dict] = []
    with requests.Session() as session:
        session.headers.update({"Content-Type": "application/json"})

        with pg_connect() as conn:
            for idx, row in enumerate(eval_rows, start=1):
                target_key = theorem_key(row["paper_id"], row["name"])

                bm25_results = rank_theorem_results(bm25_index, conn, config.bm25_config, row["query"])
                dense_results = fetch_dense_results(session, conn, config, row["query"])
                fused_results = reciprocal_rank_fusion(
                    bm25_results=bm25_results,
                    dense_results=dense_results,
                    rrf_k=config.rrf_k,
                    top_k=config.eval_top_k,
                )

                bm25_match_rank = _find_rank(bm25_results, target_key)
                dense_match_rank = _find_rank(dense_results, target_key)
                fused_match_rank = _find_rank(fused_results, target_key)
                match_position = fused_match_rank if fused_match_rank is not None else "miss"
                print(f"[{idx}/{len(eval_rows)}] RRF match position: {match_position}")

                per_query.append(
                    {
                        "query": row["query"],
                        "paper_id": row["paper_id"],
                        "name": row["name"],
                        "bm25_match_rank": bm25_match_rank,
                        "dense_match_rank": dense_match_rank,
                        "dense_results_available": bool(dense_results),
                        "match_rank": fused_match_rank,
                        "hit@1": 1.0 if fused_match_rank is not None and fused_match_rank <= 1 else 0.0,
                        "hit@10": 1.0 if fused_match_rank is not None and fused_match_rank <= 10 else 0.0,
                        "hit@20": 1.0 if fused_match_rank is not None and fused_match_rank <= 20 else 0.0,
                        "mrr@20": (1.0 / fused_match_rank) if fused_match_rank is not None and fused_match_rank <= 20 else 0.0,
                        "top_results": [asdict(result) for result in fused_results],
                    }
                )

                if idx % 10 == 0 or idx == len(eval_rows):
                    print(f"Evaluated {idx}/{len(eval_rows)} RRF queries...")

                if idx < len(eval_rows) and config.inter_query_delay_seconds > 0:
                    print(f"Sleeping {config.inter_query_delay_seconds:.1f}s before the next query...")
                    time.sleep(config.inter_query_delay_seconds)

    elapsed = time.time() - started_at
    metrics = _compute_metrics(per_query)

    return {
        "config": {
            "rrf": asdict(config),
            "bm25": asdict(config.bm25_config),
        },
        "num_queries": len(per_query),
        "num_dense_failures": sum(not row["dense_results_available"] for row in per_query),
        "elapsed_seconds": elapsed,
        "metrics": metrics,
        "per_query": per_query,
    }


def run_local_rrf_csv_evaluation(config: RRFExperimentConfig) -> dict:
    _validate_config(config)
    _validate_local_dense_config(config)
    started_at = time.time()

    eval_rows = _read_csv_rows(config.csv_path)
    bm25_index = build_index(config.bm25_config)
    model = _load_local_embedding_model(config)

    per_query: list[dict] = []
    with pg_connect() as conn:
        for idx, row in enumerate(eval_rows, start=1):
            target_key = theorem_key(row["paper_id"], row["name"])

            bm25_results = rank_theorem_results(bm25_index, conn, config.bm25_config, row["query"])
            dense_results_available = True
            try:
                dense_results = fetch_local_dense_results(conn, model, config, row["query"])
            except Exception as exc:
                if not config.continue_on_dense_error:
                    raise
                dense_results = []
                dense_results_available = False
                print(
                    f"Warning: local dense search failed for query {row['query']!r}: {exc}. "
                    "Falling back to BM25-only for this query."
                )

            fused_results = reciprocal_rank_fusion(
                bm25_results=bm25_results,
                dense_results=dense_results,
                rrf_k=config.rrf_k,
                top_k=config.eval_top_k,
            )

            bm25_match_rank = _find_rank(bm25_results, target_key)
            dense_match_rank = _find_rank(dense_results, target_key)
            fused_match_rank = _find_rank(fused_results, target_key)
            match_position = fused_match_rank if fused_match_rank is not None else "miss"
            print(f"[{idx}/{len(eval_rows)}] Local Gemma RRF match position: {match_position}")

            per_query.append(
                {
                    "query": row["query"],
                    "paper_id": row["paper_id"],
                    "name": row["name"],
                    "bm25_match_rank": bm25_match_rank,
                    "dense_match_rank": dense_match_rank,
                    "dense_results_available": dense_results_available,
                    "match_rank": fused_match_rank,
                    "hit@1": 1.0 if fused_match_rank is not None and fused_match_rank <= 1 else 0.0,
                    "hit@10": 1.0 if fused_match_rank is not None and fused_match_rank <= 10 else 0.0,
                    "hit@20": 1.0 if fused_match_rank is not None and fused_match_rank <= 20 else 0.0,
                    "mrr@20": (1.0 / fused_match_rank) if fused_match_rank is not None and fused_match_rank <= 20 else 0.0,
                    "top_results": [asdict(result) for result in fused_results],
                }
            )

            if idx % 10 == 0 or idx == len(eval_rows):
                print(f"Evaluated {idx}/{len(eval_rows)} local RRF queries...")

            if idx < len(eval_rows) and config.inter_query_delay_seconds > 0:
                print(f"Sleeping {config.inter_query_delay_seconds:.1f}s before the next query...")
                time.sleep(config.inter_query_delay_seconds)

    elapsed = time.time() - started_at
    metrics = _compute_metrics(per_query)

    return {
        "config": {
            "rrf": asdict(config),
            "bm25": asdict(config.bm25_config),
        },
        "num_queries": len(per_query),
        "num_dense_failures": sum(not row["dense_results_available"] for row in per_query),
        "elapsed_seconds": elapsed,
        "metrics": metrics,
        "per_query": per_query,
    }


def run_dense_csv_evaluation(config: RRFExperimentConfig) -> dict:
    _validate_config(config)
    started_at = time.time()

    eval_rows = _read_csv_rows(config.csv_path)

    per_query: list[dict] = []
    with requests.Session() as session:
        session.headers.update({"Content-Type": "application/json"})

        with pg_connect() as conn:
            for idx, row in enumerate(eval_rows, start=1):
                target_key = theorem_key(row["paper_id"], row["name"])

                dense_results = fetch_dense_results(session, conn, config, row["query"])
                dense_match_rank = _find_rank(dense_results, target_key)
                match_position = dense_match_rank if dense_match_rank is not None else "miss"
                print(f"[{idx}/{len(eval_rows)}] Dense match position: {match_position}")

                per_query.append(
                    {
                        "query": row["query"],
                        "paper_id": row["paper_id"],
                        "name": row["name"],
                        "dense_match_rank": dense_match_rank,
                        "dense_results_available": bool(dense_results),
                        "match_rank": dense_match_rank,
                        "hit@1": 1.0 if dense_match_rank is not None and dense_match_rank <= 1 else 0.0,
                        "hit@10": 1.0 if dense_match_rank is not None and dense_match_rank <= 10 else 0.0,
                        "hit@20": 1.0 if dense_match_rank is not None and dense_match_rank <= 20 else 0.0,
                        "mrr@20": (1.0 / dense_match_rank) if dense_match_rank is not None and dense_match_rank <= 20 else 0.0,
                        "top_results": [asdict(result) for result in dense_results[: config.eval_top_k]],
                    }
                )

                if idx % 10 == 0 or idx == len(eval_rows):
                    print(f"Evaluated {idx}/{len(eval_rows)} dense queries...")

                if idx < len(eval_rows) and config.inter_query_delay_seconds > 0:
                    print(f"Sleeping {config.inter_query_delay_seconds:.1f}s before the next query...")
                    time.sleep(config.inter_query_delay_seconds)

    elapsed = time.time() - started_at
    metrics = _compute_metrics(per_query)

    return {
        "config": {"dense": asdict(config)},
        "num_queries": len(per_query),
        "num_dense_failures": sum(not row["dense_results_available"] for row in per_query),
        "elapsed_seconds": elapsed,
        "metrics": metrics,
        "per_query": per_query,
    }


def print_rrf_evaluation_report(evaluation: dict, max_examples: int = 5) -> None:
    print(f"Queries evaluated: {evaluation['num_queries']}")
    print(f"Dense failures: {evaluation['num_dense_failures']}")
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
        print(f"BM25 rank: {row['bm25_match_rank']}")
        print(f"Dense rank: {row['dense_match_rank']}")
        if not row["dense_results_available"]:
            print("Dense search: unavailable for this query, fused ranking fell back to BM25-only")
        if row["top_results"]:
            top = row["top_results"][0]
            print(
                "Top-1 fused: "
                f"{top['paper_id']} | {top['theorem_name']} "
                f"(rrf_score={top['rrf_score']:.6f}, "
                f"bm25_rank={top['bm25_rank']}, dense_rank={top['dense_rank']})"
            )
        else:
            print("Top-1 fused: no result")
        print("")


def print_dense_evaluation_report(evaluation: dict, max_examples: int = 5) -> None:
    print(f"Queries evaluated: {evaluation['num_queries']}")
    print(f"Dense failures: {evaluation['num_dense_failures']}")
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
        print(f"Dense rank: {row['dense_match_rank']}")
        if not row["dense_results_available"]:
            print("Dense search: unavailable for this query")
        if row["top_results"]:
            top = row["top_results"][0]
            print(
                "Top-1 dense: "
                f"{top['paper_id']} | {top['theorem_name']} "
                f"(score={top['score']})"
            )
        else:
            print("Top-1 dense: no result")
        print("")
