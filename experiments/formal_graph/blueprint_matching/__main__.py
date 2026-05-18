"""Benchmark similarity metrics on apap blueprint-slogan ↔ formal-slogan
matching against the ``methods=['blueprint']`` ground truth.

Usage::

    python -m experiments.formal_graph.blueprint_matching

Every metric runs every time:
  - String/IR: edit_norm, jaccard_tokens, char_3gram, char_4gram, difflib_ratio,
    tfidf_cosine, bm25
  - Embedding cosine: Nebius Qwen/Qwen3-Embedding-8B (needs NEBIUS_API_KEY)
  - LLM judge (discrete confidence): Nebius Qwen/Qwen3-235B-A22B-Instruct-2507
    (needs NEBIUS_API_KEY)

Each metric is run once per formal prompt mode (``pilot-isolated``,
``pilot-slogan_context``, ``pilot-code_context``). Embedding and judge calls
cache to ``cache/`` so re-runs are fast.
"""
from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Callable, Dict, List, Sequence, Set, Tuple

import numpy as np

from . import metrics
from .data import load_all


MetricFn = Callable[[List[str], List[str]], np.ndarray]

METRICS: List[Tuple[str, MetricFn]] = [
    ("edit_norm",          metrics.edit_norm),
    ("jaccard_tokens",     metrics.jaccard_tokens),
    ("char_3gram",         lambda a, b: metrics.char_ngram_jaccard(a, b, 3)),
    ("char_4gram",         lambda a, b: metrics.char_ngram_jaccard(a, b, 4)),
    ("difflib_ratio",      metrics.difflib_ratio),
    ("tfidf_cosine",       metrics.tfidf_cosine),
    ("bm25",               metrics.bm25),
    ("nebius_qwen3_embed", lambda a, b: metrics.nebius_embedding_cos(a, b, "Qwen/Qwen3-Embedding-8B")),
    ("judge_qwen3_235b",   lambda a, b: metrics.llm_judge(a, b, "Qwen/Qwen3-235B-A22B-Instruct-2507")),
]


def score(
    sim: np.ndarray,
    informal_ids: Sequence[str],
    formal_ids: Sequence[str],
    truth: Set[Tuple[str, str]],
) -> Dict[str, float]:
    """Per-informal: rank formals by descending similarity. Top-k counts a hit
    if any of the informal's ground-truth formals is at rank ≤ k. MRR uses
    the best (lowest) rank among the gold formals. Informal statements whose
    gold formal isn't in the current corpus are excluded from the denominator."""
    gold: Dict[str, set] = {iid: set() for iid in informal_ids}
    for iid, fid in truth:
        if iid in gold:
            gold[iid].add(fid)

    top1 = top3 = top5 = 0
    rr_sum = 0.0
    true_scores: List[float] = []
    false_scores: List[float] = []
    evaluated = 0
    formal_id_set = set(formal_ids)

    for i, iid in enumerate(informal_ids):
        targets = gold[iid] & formal_id_set
        if not targets:
            continue
        evaluated += 1
        order = np.argsort(-sim[i])
        ranks: List[int] = []
        for rank, j in enumerate(order, start=1):
            fid = formal_ids[j]
            if fid in targets:
                ranks.append(rank)
                true_scores.append(float(sim[i, j]))
            else:
                false_scores.append(float(sim[i, j]))
        best = min(ranks)
        if best == 1: top1 += 1
        if best <= 3: top3 += 1
        if best <= 5: top5 += 1
        rr_sum += 1.0 / best

    n = evaluated or 1
    mean_t = float(np.mean(true_scores)) if true_scores else 0.0
    mean_f = float(np.mean(false_scores)) if false_scores else 0.0
    return {
        "evaluated":  evaluated,
        "top1":       top1 / n,
        "top3":       top3 / n,
        "top5":       top5 / n,
        "mrr":        rr_sum / n,
        "mean_true":  mean_t,
        "mean_false": mean_f,
        "gap":        mean_t - mean_f,
    }


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:+.3f}" if v != 0 and abs(v) < 10 else f"{v:.3f}"
    return str(v)


def _print_table(rows: List[Dict]) -> None:
    cols = ("metric", "formal_mode", "evaluated", "top1", "top3", "top5",
            "mrr", "mean_true", "mean_false", "gap", "wall_s")
    widths = {c: max(len(c), max((len(_fmt(r[c])) for r in rows), default=0)) for c in cols}
    sep = "  "
    print(sep.join(c.ljust(widths[c]) for c in cols))
    print(sep.join("-" * widths[c] for c in cols))
    for r in rows:
        print(sep.join(_fmt(r[c]).ljust(widths[c]) for c in cols))


def main() -> None:
    informal, formal, truth = load_all()
    print(f"Loaded: {len(informal)} informal slogans, {len(formal)} formal decls, "
          f"{len(truth)} ground-truth pairs")
    if not informal or not formal or not truth:
        print("Not enough data to run the benchmark.")
        return

    informal_ids   = [s.statement_id for s in informal]
    informal_texts = [s.slogan for s in informal]
    formal_modes   = sorted({mode for s in formal for mode in s.slogans})
    print(f"Formal modes: {formal_modes}")

    rows: List[Dict] = []
    for mode in formal_modes:
        mode_formals = [s for s in formal if mode in s.slogans]
        formal_ids   = [s.statement_id for s in mode_formals]
        formal_texts = [s.slogans[mode] for s in mode_formals]
        print(f"\n=== formal_mode = {mode} ({len(formal_texts)} decls) ===")
        for label, fn in METRICS:
            t0 = time.perf_counter()
            sim = fn(informal_texts, formal_texts)
            elapsed = time.perf_counter() - t0
            s = score(sim, informal_ids, formal_ids, truth)
            rows.append({"metric": label, "formal_mode": mode, "wall_s": elapsed, **s})
            print(f"  {label:20s}  top1={s['top1']:.2f}  top3={s['top3']:.2f}  "
                  f"mrr={s['mrr']:.2f}  gap={s['gap']:+.2f}  ({elapsed:.2f}s, n={s['evaluated']})")

    print("\n" + "=" * 110)
    print("Full results (sorted by top1 desc, then mrr desc):")
    print("=" * 110)
    _print_table(sorted(rows, key=lambda r: (-r["top1"], -r["mrr"], r["wall_s"])))

    out_path = Path(__file__).parent / "results.csv"
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
