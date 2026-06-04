"""Stacked verdict bars vs similarity: one 100%-stacked bar per 0.01 sim bin.

Each bar = composition of that bin's verdicts (exact green / inexact orange /
edge-ambiguous gray / wrong red). Easier to read than overlapping lines: the
green+orange height IS the match rate; red growing left->right is the story.
Bins inverted: 1.00 (left) -> 0.90 (right). Two runs (OG vs corrected).
"""
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = __file__.rsplit("/", 1)[0]
CUTOFF = 0.90
BW = 0.01
RUNS = [
    ("consensus_ge90_v2_all.jsonl", "OG run (slogan-only pilot)", "verdict_bars_og.png"),
    ("consensus_bodied.jsonl", "Corrected run (Lean signature recovered)", "verdict_bars_corrected.png"),
]


def binned(fname):
    rows = []
    for l in open(f"{HERE}/data/{fname}"):
        l = l.strip()
        if not l:
            continue
        c = json.loads(l)
        s = float(c["sim"])
        if s >= CUTOFF:
            rows.append((s, c["edge"], c.get("final")))
    edges = np.arange(0.90, 1.0001, BW)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        sub = [r for r in rows if lo <= r[0] < hi or (hi >= 1.0 and r[0] == 1.0)]
        n = len(sub)
        if n == 0:
            continue
        ex = sum(1 for _, _, f in sub if f == "exact")
        ix = sum(1 for _, _, f in sub if f == "inexact")
        wr = sum(1 for _, e, _ in sub if e is False)
        amb = n - ex - ix - wr  # edge-ambiguous (agreed match, split strength)
        out.append(((lo + hi) / 2, n, 100 * ex / n, 100 * ix / n, 100 * amb / n, 100 * wr / n))
    return out


for fname, title, out in RUNS:
    b = binned(fname)
    centers = [r[0] for r in b]
    ns = [r[1] for r in b]
    ex = np.array([r[2] for r in b]); ix = np.array([r[3] for r in b])
    amb = np.array([r[4] for r in b]); wr = np.array([r[5] for r in b])
    xpos = np.arange(len(b))[::-1]  # reverse so high sim is on the LEFT
    labels = [f"{c:.2f}\n–{c+0.005:.2f}" for c in centers]  # bin range labels
    labels = [f"{c-0.005:.2f}–{c+0.005:.2f}" for c in centers]

    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    w = 0.82
    ax.bar(xpos, ex, w, color="#2a8f5a", label="exact", zorder=3)
    ax.bar(xpos, ix, w, bottom=ex, color="#e08a2b", label="inexact", zorder=3)
    ax.bar(xpos, amb, w, bottom=ex + ix, color="#9aa0a6", label="edge-ambiguous", zorder=3)
    ax.bar(xpos, wr, w, bottom=ex + ix + amb, color="#c0392b", label="wrong", zorder=3)
    # match-rate (exact+inexact+amb) marker on each bar
    for xp, e, i, a in zip(xpos, ex, ix, amb):
        ax.text(xp, e + i + a + 1.5, f"{e+i+a:.0f}", ha="center", va="bottom",
                fontsize=7.5, color="#222")

    ax.set_xticks(xpos)
    ax.set_xticklabels(labels, rotation=45, fontsize=7.5, ha="right")
    ax.set_ylim(0, 104)
    ax.set_ylabel("share of bin (%)")
    ax.set_xlabel("cosine similarity bin  (high → low)")
    ax.set_title(f"{title}\n(n={sum(ns):,}, sim ≥ {CUTOFF}; number above bar = match rate)")
    ax.legend(loc="lower left", frameon=True, fontsize=8.5, ncol=4,
              bbox_to_anchor=(0, -0.34))
    ax.grid(True, axis="y", alpha=0.3, zorder=0)
    fig.tight_layout()
    fig.savefig(f"{HERE}/data/{out}", dpi=150, bbox_inches="tight")
    print(f"wrote data/{out}  ({len(b)} bins, n={sum(ns)})")
