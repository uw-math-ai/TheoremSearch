"""Pure functions over episode results for summary statistics.

All inputs are plain Python dicts/lists — no dataclass dependencies — so this
module is also safe to import on machines without DB or API access.
"""
from __future__ import annotations

from uuid import UUID


def recall_at_k(retrieved_uuids: set[UUID], true_dep_ids: set[UUID]) -> float:
    if not true_dep_ids:
        return 0.0
    return len(retrieved_uuids & true_dep_ids) / len(true_dep_ids)


def _dep_bucket(n: int) -> str:
    if n == 2:
        return "2"
    if n == 3:
        return "3"
    if n <= 5:
        return "4-5"
    return "6+"


def compute_summary(
    results: list[dict],
    targets: dict,  # dict[UUID, Target] — typed loosely to avoid import
) -> dict:
    """Aggregate episode results into summary statistics.

    Args:
        results: list of episode dicts as returned by run_episode().
        targets: the original targets dict from load_all_data(), used for
                 dep-count bucket stratification.
    """
    if not results:
        return {"n_targets": 0, "error": "no results"}

    recalls: list[float] = []
    queries_per_ep: list[int] = []
    unique_rates: list[float] = []
    fps_per_ep: list[float] = []
    terminal_rewards: list[float] = []
    total_dropped = 0
    total_results = 0
    total_low_conf = 0
    total_matches = 0

    by_bucket: dict[str, list[float]] = {"2": [], "3": [], "4-5": [], "6+": []}

    for ep in results:
        recall = ep.get("recall", 0.0)
        recalls.append(recall)

        n_true = ep.get("n_true_deps", 0)
        bucket = _dep_bucket(n_true)
        by_bucket[bucket].append(recall)

        tq = ep.get("total_queries", 0)
        uq = ep.get("unique_queries", 0)
        queries_per_ep.append(tq)
        unique_rates.append(uq / tq if tq > 0 else 0.0)
        fps_per_ep.append(ep.get("total_fps", 0))
        terminal_rewards.append(ep.get("terminal_reward", 0.0))
        total_dropped += ep.get("total_dropped_no_match", 0)
        total_low_conf += ep.get("n_low_confidence_matches", 0)
        total_matches += ep.get("n_total_matches", 0)

        # Total results = sum over trajectory steps
        for step in ep.get("trajectory", []):
            total_results += len(step.get("returned_results", []))

    def _mean(lst: list) -> float:
        return sum(lst) / len(lst) if lst else 0.0

    recall_by_bucket = {
        k: _mean(v) if v else None for k, v in by_bucket.items()
    }

    return {
        "n_targets": len(results),
        "mean_recall": _mean(recalls),
        "recall_by_dep_bucket": recall_by_bucket,
        "mean_queries_per_episode": _mean(queries_per_ep),
        "unique_query_rate": _mean(unique_rates),
        "mean_fp_per_episode": _mean(fps_per_ep),
        "mean_terminal_reward": _mean(terminal_rewards),
        "dropped_no_match_rate": total_dropped / total_results if total_results > 0 else 0.0,
        "low_confidence_match_rate": total_low_conf / total_matches if total_matches > 0 else 0.0,
        # Raw counts for auditing
        "total_dropped_no_match": total_dropped,
        "total_low_confidence_matches": total_low_conf,
        "total_accepted_matches": total_matches,
    }
