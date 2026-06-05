"""V2 -- Judge-as-reranker on a shortlist (why top-5 beats rank-1).

For one formal node, the top-5 HNSW informal neighbors with cosine + judge
verdict chip. Rank-1 is wrong; the real matches are rank 2-3. Makes the
Hit@1 vs Hit@10 gap visceral.

MOCK DATA -- replace with a real node where rank-1 was wrong but 2-3 matched,
from the sweep shards (top-10) + Arm-C verdicts.

Output: data/judge_reranker.png
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

BLUE = "#3f72a0"; GREEN = "#2a8f5a"; ORANGE = "#e0a52e"; WRONG = "#b5544b"
INK = "#222222"; GRAY = "#666666"; HILITE = "#eef6f0"
HERE = __file__.rsplit("/", 1)[0]

# (rank, cosine, verdict, colour, glyph, note, recovered)
ROWS = [
    (1, "0.94", "wrong",   WRONG,  "✗", "sibling concept",      False),
    (2, "0.93", "exact",   GREEN,  "✓", "recovered match",      True),
    (3, "0.92", "inexact", ORANGE, "◐", "also a match",         True),
    (4, "0.91", "wrong",   WRONG,  "✗", "different lemma",      False),
    (5, "0.90", "wrong",   WRONG,  "✗", "shared notation only", False),
]

fig, ax = plt.subplots(figsize=(8.2, 4.8))
ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")

# formal query header
ax.text(0.06, 0.93, "formal query", fontsize=9.5, color=GRAY, style="italic")
ax.text(0.06, 0.875, "LinearMap.toMatrix_adjoint", fontsize=12,
        family="monospace", fontweight="bold", color=BLUE)
ax.text(0.06, 0.815, "top-5 informal neighbors (HNSW)", fontsize=9, color=GRAY)

y0, dy = 0.70, 0.135
for (rk, cos, verd, col, gly, note, recov) in ROWS:
    y = y0 - (rk - 1) * dy
    if recov:
        ax.add_patch(FancyBboxPatch((0.04, y - 0.052), 0.92, 0.104,
                     boxstyle="round,pad=0.004,rounding_size=0.014",
                     facecolor=HILITE, edgecolor="none", zorder=0))
    ax.text(0.075, y, f"rank {rk}", fontsize=10.5, fontweight="bold",
            color=INK, va="center")
    ax.text(0.225, y, f"cos {cos}", fontsize=10.5, family="monospace",
            color=GRAY, va="center")
    # verdict chip
    ax.add_patch(FancyBboxPatch((0.40, y - 0.030), 0.165, 0.060,
                 boxstyle="round,pad=0.004,rounding_size=0.02",
                 facecolor=col, edgecolor="none", zorder=2))
    ax.text(0.4825, y, f"{gly} {verd}", fontsize=10, fontweight="bold",
            color="white", ha="center", va="center", zorder=3)
    if recov:
        ax.text(0.60, y, f"←  {note}", fontsize=10, color=col,
                fontweight="bold", va="center")
    else:
        ax.text(0.60, y, note, fontsize=9.5, color=GRAY, style="italic",
                va="center")

fig.text(0.5, 0.02,
         "Restricting to rank-1 discards real matches; judging the shortlist "
         "recovers them and surfaces multiple restatements.",
         ha="center", fontsize=9.5, color=GRAY, style="italic")
fig.savefig(f"{HERE}/figures/judge_reranker.png", dpi=150, bbox_inches="tight")
print("wrote figures/judge_reranker.png")
