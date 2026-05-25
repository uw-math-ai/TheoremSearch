"""Bootstrap 95% CIs for every headline metric in bidirectional_matching.md.

Resamples the underlying per-query results (with replacement, 2,000
resamples by default) and reports a single JSON with the CI for each
metric. Computes:

  Single-direction retrieval
    - f→i Hit@1, Hit@5, Hit@10, MRR@10  (over 1,562 evaluable gold formals)
    - i→f Hit@1, Hit@5, Hit@10, MRR@10  (over 1,308 evaluable gold informals)

  Agreement bucket counts (over 1,595 gold pairs)
    - both_correct, f2i_only, i2f_only, neither, either_direction

  Mutual rank-1 over the 1,595 gold pairs
    - mutual_n (count), gold_recall (mutual ∩ gold / |gold|)

  Cross-project twins (over 36,708 project formals, rank-1 only)
    - twins_at_0.95, twins_at_0.90, twins_at_0.85, twins_at_0.80
    - and corrected versions excluding the two parallel-formalization
      repo-pairs

  Non-gold random f→i (over evaluable subset of n=500 sample)
    - rank1_sim_ge_0.85 fraction

  Audited precisions (over 150 / 45-pair audit samples)
    - gold both-correct, both-wrong, either-wrong
    - mutual non-gold both-correct, both-correct-or-partial, either-wrong

Output:
  data/bootstrap_ci.json         # full results
  data/bootstrap_ci_summary.md   # human-readable

Reproduce:
    python -m experiments.nl_fl_matching.analysis.bootstrap_ci --resamples 2000
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Callable, Dict, List, Sequence, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "rds"))

from utils.connect import get_rds_connection  # noqa: E402
from experiments.nl_fl_matching import gold  # noqa: E402
from experiments.nl_fl_matching.analysis.eval import fetch_rows, score_direction  # noqa: E402
from experiments.nl_fl_matching.analysis.agreement import bucket_pairs  # noqa: E402


# ─── Bootstrap helpers ───────────────────────────────────────────────────── #


def bootstrap_fraction(values: Sequence[int], resamples: int = 2000,
                       rng: np.random.Generator = None) -> Tuple[float, float, float]:
    """For a binary 0/1 sequence, return (point, lo95, hi95)."""
    rng = rng or np.random.default_rng(0)
    arr = np.asarray(values, dtype=np.float64)
    if arr.size == 0:
        return float("nan"), float("nan"), float("nan")
    idx = rng.integers(0, arr.size, size=(resamples, arr.size))
    means = arr[idx].mean(axis=1)
    return float(arr.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def bootstrap_count(values: Sequence[int], threshold: float, resamples: int = 2000,
                    rng: np.random.Generator = None) -> Tuple[int, float, float]:
    """For a sequence of similarities, return (point_count_>=thr, lo95_count, hi95_count)."""
    rng = rng or np.random.default_rng(0)
    arr = np.asarray(values, dtype=np.float64)
    if arr.size == 0:
        return 0, float("nan"), float("nan")
    idx = rng.integers(0, arr.size, size=(resamples, arr.size))
    counts = (arr[idx] >= threshold).sum(axis=1)
    point = int((arr >= threshold).sum())
    return point, float(np.percentile(counts, 2.5)), float(np.percentile(counts, 97.5))


def fmt_pct(point, lo, hi):
    return f"{point*100:.1f}% [{lo*100:.1f}, {hi*100:.1f}]"


def fmt_int(point, lo, hi):
    return f"{point:,} [{lo:,.0f}, {hi:,.0f}]"


# ─── Section 1: f→i and i→f Hit@k / MRR ─────────────────────────────────── #


def _per_query_hit(ranks_by_query: Dict[str, list], gold_lookup: Dict[str, set],
                   k_max: int) -> List[Tuple[int, int, int, float]]:
    """For each evaluated query: (h1, h5, h10, rr10)."""
    out = []
    for qid in gold_lookup:
        gold_set = gold_lookup[qid]
        ranked = ranks_by_query.get(qid, [])
        if not ranked:
            continue  # evaluated set only
        best = None
        for rank, cid, _sim in ranked:
            if cid in gold_set:
                best = rank
                break
        h1  = int(best is not None and best <= 1)
        h5  = int(best is not None and best <= 5)
        h10 = int(best is not None and best <= 10)
        rr  = (1.0 / best) if (best is not None and best <= k_max) else 0.0
        out.append((h1, h5, h10, rr))
    return out


def hit_at_k_cis(per_query, rng, resamples):
    h1  = [r[0] for r in per_query]
    h5  = [r[1] for r in per_query]
    h10 = [r[2] for r in per_query]
    rr  = [r[3] for r in per_query]
    return {
        "n": len(per_query),
        "hit@1":   bootstrap_fraction(h1,  resamples, rng),
        "hit@5":   bootstrap_fraction(h5,  resamples, rng),
        "hit@10":  bootstrap_fraction(h10, resamples, rng),
        "mrr@10":  bootstrap_fraction(rr,  resamples, rng),
    }


# ─── Section 2: Agreement bucketing ─────────────────────────────────────── #


def agreement_per_pair(pairs, f2i_ranks, i2f_ranks, fml_to_gold_inf, inf_to_gold_fml):
    """Per gold pair: (both, f2i_only, i2f_only, neither) one-hot tuple."""
    out = []
    for inf_sid, fml_sid in pairs:
        f2i_top = None
        for rank, cid, _ in f2i_ranks.get(fml_sid, []):
            if rank == 1: f2i_top = cid; break
        i2f_top = None
        for rank, cid, _ in i2f_ranks.get(inf_sid, []):
            if rank == 1: i2f_top = cid; break
        f2i_ok = f2i_top is not None and f2i_top in fml_to_gold_inf.get(fml_sid, set())
        i2f_ok = i2f_top is not None and i2f_top in inf_to_gold_fml.get(inf_sid, set())
        bucket = (
            int(f2i_ok and i2f_ok),
            int(f2i_ok and not i2f_ok),
            int(not f2i_ok and i2f_ok),
            int(not f2i_ok and not i2f_ok),
            int(f2i_ok or i2f_ok),  # either
        )
        out.append(bucket)
    return out


# ─── Section 3: Cross-project twins ─────────────────────────────────────── #


def fetch_cross_project_sims(conn, exclude_parallel: bool) -> List[float]:
    PAIRS = [
        ("Sphere-Packing-Lean", "sphere-packing-math-inc"),
        ("sphere-packing-math-inc", "Sphere-Packing-Lean"),
        ("add-combi", "apap"),
        ("apap", "add-combi"),
    ]
    where_extra = ""
    params = {"model": "qwen3-8b", "pool": "cross_project_f2f"}
    if exclude_parallel:
        clauses = []
        for i, (a, b) in enumerate(PAIRS):
            clauses.append(f"(qp.external_id = %(qa{i})s AND cp.external_id = %(qb{i})s)")
            params[f"qa{i}"] = a; params[f"qb{i}"] = b
        where_extra = " AND NOT (" + " OR ".join(clauses) + ")"
    sql = f"""
    SELECT m.similarity
      FROM nl_fl_match_pilot m
      JOIN statement qs ON qs.statement_id=m.query_statement_id
      JOIN paper qp ON qp.paper_id=qs.paper_id
      JOIN statement cs ON cs.statement_id=m.candidate_statement_id
      JOIN paper cp ON cp.paper_id=cs.paper_id
     WHERE m.direction='f2f' AND m.pool_descriptor=%(pool)s
       AND m.embedding_model=%(model)s AND m.rank=1
       {where_extra}
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [r[0] for r in cur.fetchall()]


# ─── Section 4: Non-gold sim≥0.85 rate ───────────────────────────────────── #


def fetch_nongold_rank1_sims(conn) -> List[float]:
    sql = """
    SELECT similarity FROM nl_fl_match_pilot
     WHERE direction='f2i' AND pool_descriptor='nongold_random_f2i'
       AND embedding_model='qwen3-8b' AND rank=1
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        return [r[0] for r in cur.fetchall()]


# ─── Section 5: Audit-derived precisions ─────────────────────────────────── #


def load_audit_labels(csv_path: Path) -> List[Tuple[str, str]]:
    rows = []
    with csv_path.open() as fh:
        for r in csv.DictReader(fh):
            rows.append((r["primary_label"], r["secondary_label"]))
    return rows


def audit_indicators(labels: List[Tuple[str, str]]):
    """Return per-pair 0/1 indicators for several derived precisions."""
    both_correct        = []
    both_correct_partial = []
    either_wrong        = []
    both_wrong          = []
    for a, b in labels:
        both_correct.append(int(a == "correct" and b == "correct"))
        both_correct_partial.append(int(a in ("correct","partial") and b in ("correct","partial")))
        either_wrong.append(int("wrong" in (a, b)))
        both_wrong.append(int(a == "wrong" and b == "wrong"))
    return both_correct, both_correct_partial, either_wrong, both_wrong


# ─── Main ────────────────────────────────────────────────────────────────── #


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--resamples", type=int, default=2000)
    p.add_argument("--seed",      type=int, default=42)
    p.add_argument("--out-json",  type=Path,
                   default=REPO_ROOT / "experiments/nl_fl_matching/data/bootstrap_ci.json")
    p.add_argument("--out-md",    type=Path,
                   default=REPO_ROOT / "experiments/nl_fl_matching/data/bootstrap_ci.md")
    args = p.parse_args()
    rng = np.random.default_rng(args.seed)
    R = args.resamples

    conn = get_rds_connection("v2")
    print(f"[1] loading gold + ranks (resamples={R})...", flush=True)
    g = gold.load_gold(conn, embedding_model="qwen3-8b")
    f2i = fetch_rows(conn, "f2i", "qwen3-8b",
                     pool_descriptor="gold_subset_f2i", exclusion="statement")
    i2f = fetch_rows(conn, "i2f", "qwen3-8b",
                     pool_descriptor="gold_subset_i2f", exclusion="statement")
    print(f"  gold pairs: {len(g.pairs)}, f2i queries with rows: {len(f2i)}, "
          f"i2f: {len(i2f)}", flush=True)

    result = {"resamples": R, "seed": args.seed}

    # --- f→i ---
    pq_f2i = _per_query_hit(f2i, g.formal_to_gold_informals, k_max=10)
    result["f2i"] = hit_at_k_cis(pq_f2i, rng, R)

    # --- i→f ---
    pq_i2f = _per_query_hit(i2f, g.informal_to_gold_formals, k_max=10)
    result["i2f"] = hit_at_k_cis(pq_i2f, rng, R)

    # --- agreement bucketing ---
    print("[2] agreement bucketing...", flush=True)
    agree_rows = agreement_per_pair(
        g.pairs, f2i, i2f,
        g.formal_to_gold_informals, g.informal_to_gold_formals,
    )
    bc  = [r[0] for r in agree_rows]
    fo  = [r[1] for r in agree_rows]
    io_ = [r[2] for r in agree_rows]
    ne  = [r[3] for r in agree_rows]
    ei  = [r[4] for r in agree_rows]
    result["agreement"] = {
        "n":               len(agree_rows),
        "both_correct":    bootstrap_fraction(bc, R, rng),
        "f2i_only":        bootstrap_fraction(fo, R, rng),
        "i2f_only":        bootstrap_fraction(io_, R, rng),
        "neither":         bootstrap_fraction(ne, R, rng),
        "either_direction": bootstrap_fraction(ei, R, rng),
    }

    # --- mutual rank-1 (from the same data) ---
    print("[3] mutual rank-1 recall...", flush=True)
    # A pair is "mutual" if its specific (inf, fml) both appear as rank-1.
    mutual_indicator = []
    for inf_sid, fml_sid in g.pairs:
        f2i_top = None
        for rank, cid, _ in f2i.get(fml_sid, []):
            if rank == 1: f2i_top = cid; break
        i2f_top = None
        for rank, cid, _ in i2f.get(inf_sid, []):
            if rank == 1: i2f_top = cid; break
        is_mut = (f2i_top == inf_sid) and (i2f_top == fml_sid)
        mutual_indicator.append(int(is_mut))
    result["mutual_nn_gold_recall"] = bootstrap_fraction(mutual_indicator, R, rng)

    # --- cross-project twins (raw + corrected) ---
    print("[4] cross-project twin sim distribution...", flush=True)
    sims_all = fetch_cross_project_sims(conn, exclude_parallel=False)
    sims_corr = fetch_cross_project_sims(conn, exclude_parallel=True)
    result["cross_project_twins"] = {"all_n": len(sims_all), "corrected_n": len(sims_corr)}
    for label, sims in (("all", sims_all), ("corrected", sims_corr)):
        for thr in (0.95, 0.90, 0.85, 0.80):
            result["cross_project_twins"][f"{label}_sim_ge_{thr:.2f}_count"] = \
                bootstrap_count(sims, thr, R, rng)

    # --- non-gold rank-1 sim≥0.85 ---
    print("[5] non-gold sweep distribution...", flush=True)
    nongold_sims = fetch_nongold_rank1_sims(conn)
    nongold_ge_85 = [int(s >= 0.85) for s in nongold_sims]
    result["nongold"] = {
        "evaluable_n":       len(nongold_sims),
        "rank1_sim_ge_0.85": bootstrap_fraction(nongold_ge_85, R, rng),
    }

    conn.close()

    # --- audit-derived precisions ---
    print("[6] audit-derived precisions...", flush=True)
    gold_audit_path = REPO_ROOT / "experiments/nl_fl_matching/data/gold_pair_audit.csv"
    mutual_audit_path = REPO_ROOT / "experiments/nl_fl_matching/data/mutual_nongold_audit.csv"
    for name, path in (("gold_pair_audit", gold_audit_path),
                       ("mutual_nongold_audit", mutual_audit_path)):
        if not path.exists():
            result[name] = {"missing": True}
            continue
        labels = load_audit_labels(path)
        bc, bcp, ew, bw = audit_indicators(labels)
        result[name] = {
            "n":                       len(labels),
            "both_correct":            bootstrap_fraction(bc,  R, rng),
            "both_correct_or_partial": bootstrap_fraction(bcp, R, rng),
            "either_wrong":            bootstrap_fraction(ew,  R, rng),
            "both_wrong":              bootstrap_fraction(bw,  R, rng),
        }

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(result, indent=2))
    print(f"\nwrote {args.out_json}")

    # Human-readable
    def line(name, t):
        if isinstance(t, tuple) and len(t) == 3:
            p_, l_, h_ = t
            if isinstance(p_, float):
                return f"  {name:<28}  {fmt_pct(p_, l_, h_)}"
            return f"  {name:<28}  {fmt_int(p_, l_, h_)}"
        return f"  {name}: {t}"

    md = []
    md.append("# Bootstrap 95% CIs for headline metrics\n")
    md.append(f"Resamples: {R}, seed: {args.seed}, RNG: numpy default_rng.\n")
    md.append("Generated by `experiments/nl_fl_matching/analysis/bootstrap_ci.py`.\n")

    md.append("\n## Single-direction retrieval\n")
    md.append(f"### f→i (n={result['f2i']['n']})")
    for k in ("hit@1","hit@5","hit@10","mrr@10"):
        md.append(line(k, result["f2i"][k]))
    md.append(f"\n### i→f (n={result['i2f']['n']})")
    for k in ("hit@1","hit@5","hit@10","mrr@10"):
        md.append(line(k, result["i2f"][k]))

    md.append(f"\n## Agreement bucketing (n={result['agreement']['n']})")
    for k in ("both_correct","f2i_only","i2f_only","neither","either_direction"):
        md.append(line(k, result["agreement"][k]))

    md.append(f"\n## Mutual rank-1 gold recall (n={result['agreement']['n']})")
    md.append(line("mutual_n / |gold|", result["mutual_nn_gold_recall"]))

    md.append(f"\n## Cross-project twins  (all n={result['cross_project_twins']['all_n']}, corrected n={result['cross_project_twins']['corrected_n']})")
    for label in ("all", "corrected"):
        for thr in (0.95, 0.90, 0.85, 0.80):
            md.append(line(f"{label} twins ≥ {thr:.2f}",
                           result["cross_project_twins"][f"{label}_sim_ge_{thr:.2f}_count"]))

    md.append(f"\n## Non-gold random f→i (evaluable n={result['nongold']['evaluable_n']})")
    md.append(line("rank-1 sim ≥ 0.85", result["nongold"]["rank1_sim_ge_0.85"]))

    for name, label in (("gold_pair_audit", "Gold-pair audit"),
                        ("mutual_nongold_audit", "Mutual non-gold audit")):
        a = result.get(name, {})
        if a.get("missing"):
            continue
        md.append(f"\n## {label} (n={a['n']})")
        for k in ("both_correct","both_correct_or_partial","either_wrong","both_wrong"):
            md.append(line(k, a[k]))

    args.out_md.write_text("\n".join(md) + "\n")
    print(f"wrote {args.out_md}")


if __name__ == "__main__":
    main()
