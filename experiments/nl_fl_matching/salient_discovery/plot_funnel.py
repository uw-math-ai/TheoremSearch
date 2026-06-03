"""Funnel: scale collapse from intractable pair-space to confirmed edges.

Labels live in a fixed left column (always readable); bars to the right show
magnitude on a log scale (stages span 9 orders of magnitude).
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = __file__.rsplit("/", 1)[0]

STAGES = [
    ("Naive pair space", 4_560_054_057_385, "11.75M arXiv × 388K Lean — intractable"),
    ("ANN sweep", 385_657, "one nearest-neighbor query per formal node"),
    ("Candidate found", 206_326, "rank-1 informal neighbor exists (53.5%)"),
    ("Strong candidates", 8_022, "cosine ≥ 0.90"),
    ("Confirmed matches", 5_860, "Opus-judged genuine restatements (87%)"),
]
COLORS = ["#9aa0a6", "#7aa6c2", "#5b8fb0", "#3a6ea5", "#2a8f5a"]


def fmt(n):
    if n >= 1e12: return f"{n/1e12:.2f} trillion"
    if n >= 1e6:  return f"{n/1e6:.2f}M"
    return f"{n:,}"


fig, ax = plt.subplots(figsize=(9, 4.8))
logs = [np.log10(c) for _, c, _ in STAGES]
wmax, wmin = max(logs), min(logs)
BAR_L = 0.30          # bars start here; left 30% is the label gutter
BAR_SPAN = 0.66
y = np.arange(len(STAGES))[::-1]

for yi, (label, count, note), lg, col in zip(y, STAGES, logs, COLORS):
    w = BAR_SPAN * (lg / wmax)
    ax.barh(yi, w, height=0.55, left=BAR_L, color=col, zorder=3)
    # fixed left gutter: stage name (bold) + count, right-aligned at the bar start
    ax.text(BAR_L - 0.015, yi, f"{label}\n{fmt(count)}", ha="right", va="center",
            fontsize=10.5, fontweight="bold", zorder=4)
    # note: just past the end of each bar
    ax.text(BAR_L + w + 0.012, yi, note, ha="left", va="center",
            fontsize=8.5, color="dimgray", style="italic", zorder=4)

ax.set_xlim(0, 1); ax.set_ylim(-0.6, len(STAGES) - 0.4)
ax.axis("off")
ax.set_title("From 4.56 trillion possible pairs to 5,860 confirmed edges",
             fontsize=13, fontweight="bold", pad=10)
fig.text(0.98, 0.02, "bar length ∝ log₁₀(count)", ha="right", fontsize=8, color="gray")
fig.tight_layout(rect=[0, 0.03, 1, 1])
fig.savefig(f"{HERE}/data/funnel.png", dpi=150, bbox_inches="tight")
print("wrote data/funnel.png")
