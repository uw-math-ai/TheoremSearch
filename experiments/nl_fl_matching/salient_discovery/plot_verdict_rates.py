"""verdict_rates_vs_sim: how judge verdicts break down vs cosine similarity.

Two plain line charts (OG slogan-only run vs corrected re-judge), both clipped to
the sim range we judged (>= CUTOFF), 0.01-wide bins, x inverted 1.00 -> 0.90.
Lines: match (blue) = exact+inexact; exact (green); inexact (orange); wrong (red).
"""
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = __file__.rsplit("/", 1)[0]
CUTOFF = 0.9046  # the lowest sim reached in the corrected run; clip both to this
BW = 0.01

RUNS = [
    ("consensus_ge90_v2_all.jsonl", "OG run (slogan-only pilot)", "verdict_rates_vs_sim_og.png"),
    ("consensus_bodied.jsonl", "Corrected run (Lean signature recovered)", "verdict_rates_vs_sim_corrected.png"),
]


def load(fname):
    rows = []
    for l in open(f"{HERE}/data/{fname}"):
        l = l.strip()
        if not l:
            continue
        c = json.loads(l)
        s = float(c["sim"])
        if s < CUTOFF:
            continue
        rows.append((s, c["edge"], c.get("final")))
    return rows


def binned(rows):
    edges = np.arange(0.90, 1.0001, BW)
    centers, match, exact, inexact, wrong, ns = [], [], [], [], [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        sub = [r for r in rows if lo <= r[0] < hi or (hi >= 1.0 and r[0] == 1.0)]
        n = len(sub)
        if n == 0:
            continue
        centers.append((lo + hi) / 2)
        match.append(100 * sum(1 for _, e, _ in sub if e is True) / n)
        exact.append(100 * sum(1 for _, _, f in sub if f == "exact") / n)
        inexact.append(100 * sum(1 for _, _, f in sub if f == "inexact") / n)
        wrong.append(100 * sum(1 for _, e, _ in sub if e is False) / n)
        ns.append(n)
    return (np.array(centers), np.array(match), np.array(exact),
            np.array(inexact), np.array(wrong), ns)


for fname, title, out in RUNS:
    rows = load(fname)
    x, match, exact, inexact, wrong, ns = binned(rows)
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.plot(x, match, "-o", color="tab:blue", label="match (exact+inexact)", lw=2, ms=4)
    ax.plot(x, exact, "-o", color="tab:green", label="exact", lw=1.5, ms=3)
    ax.plot(x, inexact, "-o", color="tab:orange", label="inexact", lw=1.5, ms=3)
    ax.plot(x, wrong, "-o", color="tab:red", label="wrong", lw=1.5, ms=3)
    ax.set_xlim(1.0, 0.90)  # inverted: 1.00 left -> 0.90 right
    ax.set_ylim(0, 100)
    ax.set_xlabel("cosine similarity (bin center)")
    ax.set_ylabel("share of edges in bin (%)")
    ax.set_xticks(x)  # ticks AT the bin centers so every marker lands on a tick
    ax.set_xticklabels([f"{v:.3f}" for v in x], rotation=45, fontsize=8)
    ax.set_title(f"{title}\n(n={len(rows):,}, sim ≥ {CUTOFF})")
    ax.legend(loc="lower left", frameon=False, fontsize=9)
    ax.grid(True, alpha=0.3)
    fig.text(0.5, 0.005, f"Points plotted at centers of {BW}-wide similarity bins; "
             f"leftmost bin (0.99–1.00) includes the max similarity of 1.000.",
             ha="center", fontsize=7.5, color="gray")
    fig.tight_layout(rect=[0, 0.04, 1, 1])
    fig.savefig(f"{HERE}/data/{out}", dpi=150)
    print(f"wrote data/{out}  (n={len(rows)}, {len(x)} bins)")
