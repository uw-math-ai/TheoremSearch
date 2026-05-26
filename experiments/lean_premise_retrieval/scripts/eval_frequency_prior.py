"""Frequency-prior baseline + rarity tables for the frozen module-held-out split.

The frequency prior IGNORES the query and returns the globally most-common
premises (by train-set gold frequency) for every target. It is the metric's
honesty check: whatever recall it reaches is recall any method gets "for free"
from a popularity prior, not from understanding the query. If a learned method
barely beats this, its headline number is hollow.

Parameter-free, so computing it on `test` does not contaminate anything.

Also prints premise-rarity buckets (by train frequency), used downstream to
stratify every method's recall into common vs rare premises.

Run (after build_split.py):
    python scripts/eval_frequency_prior.py
"""
import json
import pickle
import statistics as st
from collections import Counter
from pathlib import Path

CACHE = Path(__file__).resolve().parent.parent / "cache"
KS = [5, 10, 20, 50, 100]


def bucket(n):
    return "2" if n == 2 else "3" if n == 3 else "4-5" if n <= 5 else "6+"


def eval_split(name, tids, targets, popular):
    pop_sets = {k: set(popular[:k]) for k in KS}
    rec = {k: [] for k in KS}
    rec_b = {}
    for tid in tids:
        gold = set(targets[tid]["gold"])
        b = bucket(len(gold))
        rec_b.setdefault(b, {k: [] for k in KS})
        for k in KS:
            # prior list excludes the target itself implicitly (handled below)
            got = len(gold & pop_sets[k]) / len(gold)
            rec[k].append(got); rec_b[b][k].append(got)
    print(f"\n=== frequency prior on {name} (n={len(tids):,}) ===")
    print("  " + "  ".join(f"R@{k}={st.mean(rec[k]):.3f}" for k in KS))
    print("  by dep-count bucket (R@10 / R@100):")
    for b in ["2", "3", "4-5", "6+"]:
        if b in rec_b:
            n = len(rec_b[b][10])
            print(f"    {b:<5} n={n:<6} R@10={st.mean(rec_b[b][10]):.3f}  "
                  f"R@100={st.mean(rec_b[b][100]):.3f}")


def main():
    targets = pickle.load(open(CACHE / "targets_full.pkl", "rb"))
    split = json.loads((CACHE / "split.json").read_text())
    freq = json.loads((CACHE / "premise_freq_train.json").read_text())

    # popular premises by TRAIN frequency (exclude none; targets handled per-eval)
    popular = [p for p, _ in Counter(freq).most_common(max(KS))]
    print(f"top-{max(KS)} most-common train premises cover freq "
          f"[{freq[popular[0]]:,} .. {freq[popular[-1]]:,}] train-targets each")

    by_split = {s: [t for t, ss in split.items() if ss == s] for s in ("val", "test")}
    for name in ("val", "test"):
        eval_split(name, by_split[name], targets, popular)

    # ---- premise rarity distribution (for stratified recall downstream) ----
    print("\n=== premise rarity (train gold-frequency) distribution ===")
    fvals = list(freq.values())
    fvals_sorted = sorted(fvals, reverse=True)
    print(f"  distinct premises used as gold in train: {len(freq):,}")
    print(f"  freq: max={max(fvals):,} median={st.median(fvals):.0f} "
          f"p90={fvals_sorted[len(fvals)//10]:,}")
    # rarity buckets by frequency
    edges = [(1, 1), (2, 3), (4, 10), (11, 100), (101, 10**9)]
    labels = ["1", "2-3", "4-10", "11-100", "100+"]
    counts = Counter()
    for v in fvals:
        for (lo, hi), lab in zip(edges, labels):
            if lo <= v <= hi:
                counts[lab] += 1; break
    for lab in labels:
        print(f"    freq {lab:<7}: {counts[lab]:,} premises")


if __name__ == "__main__":
    main()
