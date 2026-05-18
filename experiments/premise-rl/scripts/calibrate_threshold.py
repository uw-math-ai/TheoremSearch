"""One-off script to calibrate the body-similarity match threshold.

Usage:
    python scripts/calibrate_threshold.py [--n-samples 50] [--k 10]
                                          [--out-yaml configs/smoke_test.yaml]

Samples dep statements from rl_test_100, queries each against TheoremSearch,
builds two ratio distributions (true-match vs cross-pair), checks for clean
separation, and (optionally) writes match_threshold into a YAML config.

Hard-stop if distributions overlap — see PLAN.md §2.2.b.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path

# Allow running as a top-level script from the premise-rl directory
sys.path.insert(0, str(Path(__file__).parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.data.load_targets import load_all_data
from src.env.search_client import TheoremSearchClient


# ---------------------------------------------------------------------------
# Simple percentile (avoids a numpy hard-dep in main package)
# ---------------------------------------------------------------------------

def percentile(data: list[float], p: float) -> float:
    if not data:
        raise ValueError("empty data")
    s = sorted(data)
    idx = (p / 100.0) * (len(s) - 1)
    lo = int(idx)
    hi = lo + 1
    if hi >= len(s):
        return s[-1]
    frac = idx - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def text_histogram(data: list[float], bins: int = 10, width: int = 40) -> str:
    if not data:
        return "(empty)"
    lo, hi = min(data), max(data)
    if lo == hi:
        return f"all values = {lo:.1f}"
    step = (hi - lo) / bins
    counts = [0] * bins
    for v in data:
        b = min(int((v - lo) / step), bins - 1)
        counts[b] += 1
    max_c = max(counts) or 1
    lines = []
    for i, c in enumerate(counts):
        label = f"{lo + i * step:5.1f}-{lo + (i+1)*step:5.1f}"
        bar = "#" * int(width * c / max_c)
        lines.append(f"  {label} | {bar} ({c})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main calibration logic
# ---------------------------------------------------------------------------

async def calibrate(n_samples: int, k: int, cache_dir: str) -> dict:
    _targets, dep_stmts = load_all_data()

    if not dep_stmts:
        print("ERROR: no dep statements loaded — check DB connection and rl_test_100 table")
        sys.exit(1)

    sample = random.sample(dep_stmts, min(n_samples, len(dep_stmts)))
    print(f"Sampled {len(sample)} dep statements from universe of {len(dep_stmts)}")

    client = TheoremSearchClient(cache_dir=cache_dir)
    true_match_scores: list[float] = []
    cross_pair_scores: list[float] = []

    for i, dep in enumerate(sample):
        query = dep.body[:100]
        results = await client.search(query, k=k)
        if not results:
            print(f"  [{i+1}/{len(sample)}] No results — skipping (body: {query[:40]!r})")
            continue

        scored = [(from_rapidfuzz_ratio(r.body, dep.body), r) for r in results]
        scored.sort(key=lambda x: x[0], reverse=True)

        best_score = scored[0][0]
        true_match_scores.append(best_score)
        for score, _ in scored[1:]:
            cross_pair_scores.append(score)

        print(f"  [{i+1}/{len(sample)}] best={best_score:.1f}  "
              f"cross={[f'{s:.0f}' for s, _ in scored[1:]]}")

    await client.close()

    if not true_match_scores:
        print("ERROR: got no results from any query — check TheoremSearch connectivity")
        sys.exit(1)

    p5_true = percentile(true_match_scores, 5)
    p95_cross = percentile(cross_pair_scores, 95) if cross_pair_scores else 0.0

    print("\n--- True-match distribution (best ratio per query) ---")
    print(text_histogram(true_match_scores))
    print(f"\n5th percentile:  {p5_true:.1f}")
    print(f"Mean:            {sum(true_match_scores)/len(true_match_scores):.1f}")
    print(f"Min:             {min(true_match_scores):.1f}")

    if cross_pair_scores:
        print("\n--- Cross-pair distribution (non-best ratios) ---")
        print(text_histogram(cross_pair_scores))
        print(f"\n95th percentile: {p95_cross:.1f}")
        print(f"Mean:            {sum(cross_pair_scores)/len(cross_pair_scores):.1f}")
        print(f"Max:             {max(cross_pair_scores):.1f}")

    print()
    if p5_true <= p95_cross:
        print("=" * 60)
        print("HARD STOP: distributions overlap — no clean threshold.")
        print(f"  5th percentile true matches:  {p5_true:.1f}")
        print(f"  95th percentile cross-pairs:  {p95_cross:.1f}")
        print()
        print("Likely causes:")
        print("  1. Parser-version skew: API snapshot vs current Postgres bodies differ.")
        print("  2. API indexed against a substantively different corpus version.")
        print("  3. dep_stmts bodies are too short/generic to produce discriminative queries.")
        print()
        print("Do NOT proceed to Phase 3 until this is resolved.")
        print("=" * 60)
        sys.exit(2)

    suggested = (p5_true + p95_cross) / 2.0
    print("=" * 60)
    print("Clean separation found.")
    print(f"  5th percentile true matches:  {p5_true:.1f}")
    print(f"  95th percentile cross-pairs:  {p95_cross:.1f}")
    print(f"  Suggested threshold:          {suggested:.1f}")
    print("=" * 60)

    return {
        "p5_true": p5_true,
        "p95_cross": p95_cross,
        "suggested_threshold": suggested,
        "true_match_scores": true_match_scores,
        "cross_pair_scores": cross_pair_scores,
    }


def from_rapidfuzz_ratio(s1: str, s2: str) -> float:
    from rapidfuzz import fuzz
    return fuzz.ratio(s1, s2)


# ---------------------------------------------------------------------------
# YAML patcher (writes match_threshold into the config file)
# ---------------------------------------------------------------------------

def patch_yaml_threshold(yaml_path: str, threshold: float) -> None:
    import re
    text = Path(yaml_path).read_text()
    text = re.sub(
        r"^(match_threshold\s*:).*$",
        f"\\g<1> {threshold:.1f}  # set by calibrate_threshold.py",
        text,
        flags=re.MULTILINE,
    )
    Path(yaml_path).write_text(text)
    print(f"Updated match_threshold in {yaml_path} -> {threshold:.1f}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n-samples", type=int, default=50)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--cache-dir", default=".cache/search")
    ap.add_argument("--out-yaml", default=None,
                    help="If provided, write match_threshold into this YAML file")
    ap.add_argument("--out-json", default=None,
                    help="If provided, save calibration data as JSON for later reference")
    args = ap.parse_args()

    stats = asyncio.run(calibrate(args.n_samples, args.k, args.cache_dir))

    if args.out_yaml:
        patch_yaml_threshold(args.out_yaml, stats["suggested_threshold"])

    if args.out_json:
        out = {k: v for k, v in stats.items() if not isinstance(v, list)}
        out["n_true_matches"] = len(stats["true_match_scores"])
        out["n_cross_pairs"] = len(stats["cross_pair_scores"])
        Path(args.out_json).write_text(json.dumps(out, indent=2))
        print(f"Calibration stats written to {args.out_json}")


if __name__ == "__main__":
    main()
