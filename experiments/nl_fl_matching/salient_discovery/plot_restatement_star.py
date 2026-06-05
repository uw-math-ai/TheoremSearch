"""V1 -- The restatement star (headline one-to-many figure).

One formal Lean declaration (blue, centre) fans out to several informal
restatements (red) across different papers. Spoke colour = judge verdict
(green exact / orange inexact); each leaf is tagged with its source + cosine.

MOCK DATA -- replace leaves with a real high-multiplicity formal node once the
top-5 multi-match (Arm C) run produces per-node match sets.

Output: data/restatement_star.png
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Circle, FancyArrowPatch

BLUE = "#3f72a0"; RED = "#c8553d"; GREEN = "#2a8f5a"; ORANGE = "#e0a52e"
INK = "#222222"; GRAY = "#666666"
HERE = __file__.rsplit("/", 1)[0]

# (source label, cosine, verdict word, verdict colour, glyph)
LEAVES = [
    ("arXiv:1901.05745",     "0.96", "exact",   GREEN,  "✓"),
    ("arXiv:2412.00133",     "0.91", "inexact", ORANGE, "◐"),
    ("arXiv:quant-ph/0511",  "0.94", "exact",   GREEN,  "✓"),
    ("blueprint:pfr",        "0.93", "exact",   GREEN,  "✓"),
    ("arXiv:2305.14211",     "0.90", "exact",   GREEN,  "✓"),
]
ANGLES = [64, 33, 2, -29, -60]
R = 0.40
C = (0.30, 0.55)

fig, ax = plt.subplots(figsize=(9.4, 5.6))
ax.set_xlim(0, 1.18); ax.set_ylim(0, 1); ax.set_aspect("equal"); ax.axis("off")

# spokes + leaves
for (lbl, cos, verd, col, gly), a in zip(LEAVES, ANGLES):
    x = C[0] + R * np.cos(np.radians(a))
    y = C[1] + R * np.sin(np.radians(a))
    ax.add_patch(FancyArrowPatch(C, (x, y), arrowstyle="-", lw=2.6, color=col,
                 zorder=2, shrinkA=24, shrinkB=13))
    ax.add_patch(Circle((x, y), 0.026, facecolor=RED, edgecolor="white",
                 lw=1.4, zorder=4))
    ax.text(x + 0.045, y + 0.016, lbl, ha="left", va="center", fontsize=9.5,
            family="monospace", color=INK, zorder=5)
    ax.text(x + 0.045, y - 0.028, f"cos {cos}   {gly} {verd}", ha="left",
            va="center", fontsize=8.5, color=col, fontweight="bold", zorder=5)

# central formal node
ax.add_patch(Circle(C, 0.05, facecolor=BLUE, edgecolor="white", lw=2, zorder=5))
_wbb = dict(facecolor="white", edgecolor="none", pad=2)
ax.text(C[0], C[1] + 0.10, "SimpleGraph.Walk.append_assoc", ha="center",
        va="bottom", fontsize=10, family="monospace", fontweight="bold",
        color=BLUE, zorder=7, bbox=_wbb)
ax.text(C[0], C[1] - 0.10, "formal Lean decl", ha="center", va="top",
        fontsize=9, color=GRAY, style="italic", zorder=7, bbox=_wbb)

fig.text(0.5, 0.025,
         "A single formalization links to multiple informal restatements across the "
         "literature — the judge recovers a set, not a single edge.",
         ha="center", fontsize=9.5, color=GRAY, style="italic")
fig.savefig(f"{HERE}/figures/restatement_star.png", dpi=150, bbox_inches="tight")
print("wrote figures/restatement_star.png")
