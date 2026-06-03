"""Score the gold-anchored prompt A/B pilot against ground truth.

Truth: positives (gold pairs) = EDGE; hard negatives (same-blueprint mismatch) = NOT EDGE.
For each arm: edge-recall on positives, reject-rate on negatives, balanced accuracy,
exact-rate on positives. Plus the actual errors (FP/FN) and the A-vs-B disagreements
so we can see whether the decl-name helps or biases.

  /tmp/pilot_ab.json    [{pid, armA, ra, armB, rb}]
  /tmp/pilot_truth.json {pid: {kind, truth_edge, neg_type, formal_decl, formal_slogan, informal_slogan}}
"""
from __future__ import annotations
import json
from collections import Counter

EDGE = {"exact", "inexact"}


def wilson(k, n):
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / n; z = 1.96; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return p, max(0, c - h), min(1, c + h)


def main():
    truth = {int(k): v for k, v in json.load(open("/tmp/pilot_truth.json")).items()}
    ab = {r["pid"]: r for r in json.load(open("/tmp/pilot_ab.json"))}
    pids = sorted(p for p in truth if p in ab)
    pos = [p for p in pids if truth[p]["truth_edge"]]
    neg = [p for p in pids if not truth[p]["truth_edge"]]
    print(f"scored {len(pids)} pairs  (pos={len(pos)}, neg={len(neg)})\n")

    for arm in ("armA", "armB"):
        name = {"armA": "A  slogan-only", "armB": "B  slogan+decl-name"}[arm]
        # positives: edge-recall + exact-rate
        e_pos = sum(1 for p in pos if ab[p][arm] in EDGE)
        x_pos = sum(1 for p in pos if ab[p][arm] == "exact")
        # negatives: reject (wrong) rate ; false-positive = graded edge
        w_neg = sum(1 for p in neg if ab[p][arm] == "wrong")
        fp = sum(1 for p in neg if ab[p][arm] in EDGE)
        er, erlo, erhi = wilson(e_pos, len(pos))
        rr, rrlo, rrhi = wilson(w_neg, len(neg))
        bal = (er + rr) / 2
        print(f"=== ARM {name} ===")
        print(f"  positives  edge-recall : {e_pos}/{len(pos)} = {100*er:.0f}% [{100*erlo:.0f}-{100*erhi:.0f}]   (exact {x_pos}/{len(pos)} = {100*x_pos/len(pos):.0f}%)")
        print(f"  negatives  reject(wrong): {w_neg}/{len(neg)} = {100*rr:.0f}% [{100*rrlo:.0f}-{100*rrhi:.0f}]   (false-EDGE {fp}/{len(neg)} = {100*fp/len(neg):.0f}%)")
        print(f"  BALANCED ACCURACY      : {100*bal:.1f}%")
        print(f"  label dist  pos: {dict(Counter(ab[p][arm] for p in pos))}   neg: {dict(Counter(ab[p][arm] for p in neg))}\n")

    # per-pair correctness (pos correct = edge; neg correct = wrong)
    def correct(p, arm):
        return (ab[p][arm] in EDGE) if truth[p]["truth_edge"] else (ab[p][arm] == "wrong")
    cA = sum(correct(p, "armA") for p in pids); cB = sum(correct(p, "armB") for p in pids)
    print(f"overall correct  A: {cA}/{len(pids)} = {100*cA/len(pids):.0f}%   B: {cB}/{len(pids)} = {100*cB/len(pids):.0f}%")
    # McNemar: A right/B wrong vs A wrong/B right
    a_only = sum(1 for p in pids if correct(p, "armA") and not correct(p, "armB"))
    b_only = sum(1 for p in pids if correct(p, "armB") and not correct(p, "armA"))
    print(f"A-right/B-wrong: {a_only}   B-right/A-wrong: {b_only}\n")

    # disagreements (A vs B label differ) — the informative cases
    dis = [p for p in pids if ab[p]["armA"] != ab[p]["armB"]]
    print(f"=== A vs B DISAGREEMENTS ({len(dis)}) — does the decl-name change the call? ===")
    for p in dis:
        t = truth[p]; tag = "EDGE" if t["truth_edge"] else f"NOT({t['neg_type']})"
        print(f"  pid{p} truth={tag:<16} A={ab[p]['armA']:<11} B={ab[p]['armB']:<11} {t['formal_decl'][:34]}")
        print(f"        F: {t['formal_slogan'][:100]}")
        print(f"        I: {t['informal_slogan'][:100]}")
    # errors per arm
    for arm in ("armA", "armB"):
        fn = [p for p in pos if not (ab[p][arm] in EDGE)]   # gold called not-edge
        fpos = [p for p in neg if ab[p][arm] in EDGE]        # mismatch called edge
        print(f"\n--- {arm} errors: {len(fn)} false-neg (gold->not-edge), {len(fpos)} false-pos (mismatch->edge) ---")
        for p in fpos:
            print(f"  FALSE-EDGE pid{p} {ab[p][arm]} :: {truth[p]['formal_decl'][:30]} :: {ab[p][arm[:2]+'?'] if False else ab[p]['ra' if arm=='armA' else 'rb']}"[:160])


if __name__ == "__main__":
    main()
