"""V5 -- The three arms as escalating contributions (orienting diagram).

A -> B -> C as a progression so the reader sees the arc: from verifying one
guess, to grounding the judge, to discovering the full restatement set.

Schematic. Output: data/three_arms.png
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

INK = "#222222"; GRAY = "#5a5a5a"
# escalating tints (blue family) per arm
ARMS = [
    ("A", "#7aa6c2", "rank-1, base context",
     "verify the embedding's top guess", "trust check vs. Opus"),
    ("B", "#5b8fb0", "rank-1 + symmetric context",
     "context changes verdicts", "better-grounded judging"),
    ("C", "#3f72a0", "top-5, multi-match",
     "recover missed + multiple matches", "one-to-many discovery"),
]
HERE = __file__.rsplit("/", 1)[0]

fig, ax = plt.subplots(figsize=(8.8, 4.6))
ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")

y_rows = [0.78, 0.50, 0.22]
BX, BW, BH = 0.085, 0.355, 0.17    # method box

for (tag, col, method, adds, tagline), y in zip(ARMS, y_rows):
    # arm tag chip
    ax.add_patch(FancyBboxPatch((BX - 0.07, y - BH / 2), 0.055, BH,
                 boxstyle="round,pad=0.004,rounding_size=0.02",
                 facecolor=col, edgecolor="none", zorder=3))
    ax.text(BX - 0.0425, y, tag, ha="center", va="center", fontsize=15,
            fontweight="bold", color="white", zorder=4)
    # method box
    ax.add_patch(FancyBboxPatch((BX, y - BH / 2), BW, BH,
                 boxstyle="round,pad=0.006,rounding_size=0.02",
                 facecolor=col, alpha=0.16, edgecolor=col, linewidth=1.0, zorder=3))
    ax.text(BX + BW / 2, y + 0.028, method, ha="center", va="center",
            fontsize=9.5, fontweight="bold", color=INK, zorder=4)
    ax.text(BX + BW / 2, y - 0.030, tagline, ha="center", va="center",
            fontsize=8.5, color=GRAY, style="italic", zorder=4)
    # arrow -> what it adds
    ax.add_patch(FancyArrowPatch((BX + BW + 0.015, y), (BX + BW + 0.10, y),
                 arrowstyle="-|>", mutation_scale=13, lw=1.6, color=col, zorder=3))
    ax.text(BX + BW + 0.12, y, adds, ha="left", va="center", fontsize=11,
            color=INK, fontweight="bold")

# escalation arrows down the left (A -> B -> C)
for y_hi, y_lo in zip(y_rows[:-1], y_rows[1:]):
    ax.add_patch(FancyArrowPatch((BX - 0.0425, y_hi - BH / 2 - 0.005),
                 (BX - 0.0425, y_lo + BH / 2 + 0.005),
                 arrowstyle="-|>", mutation_scale=11, lw=1.4, color=GRAY, zorder=2))

fig.text(0.5, 0.02,
         "From verifying one guess, to grounding the judge, to discovering the "
         "full restatement set.",
         ha="center", fontsize=9.5, color=GRAY, style="italic")
fig.savefig(f"{HERE}/figures/three_arms.png", dpi=150, bbox_inches="tight")
print("wrote figures/three_arms.png")
