"""V3 -- The contextualized judge (symmetric context).

The judge now sees packed dependency context on BOTH sides, mirroring how the
slogans were generated. Formal side: Lean signature + packed dep context
(deps ranked by role, plumbing filtered). Informal side: LaTeX statement +
paragraph window + abstract + informal deps. Both feed one judge -> verdict.

Schematic (no data). Added context boxes are a lighter tint to read as
"augmentation".

Output: data/contextualized_judge.png
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

BLUE = "#3f72a0"; RED = "#c8553d"; GREEN = "#2a8f5a"; ORANGE = "#e0a52e"
WRONG = "#b5544b"; INK = "#222222"; GRAY = "#666666"
HERE = __file__.rsplit("/", 1)[0]

fig, ax = plt.subplots(figsize=(8.8, 5.6))
ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")


def box(x, y, w, h, fc, ec, title, sub, tcol):
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                 boxstyle="round,pad=0.006,rounding_size=0.02",
                 facecolor=fc, edgecolor=ec, linewidth=1.0, zorder=3))
    ax.text(x, y + 0.018, title, ha="center", va="center", fontsize=9.5,
            fontweight="bold", color=tcol, zorder=4)
    ax.text(x, y - 0.026, sub, ha="center", va="center", fontsize=7.6,
            color=GRAY, style="italic", zorder=4)


LX, RX = 0.255, 0.745

# side headers
ax.text(LX, 0.955, "FORMAL", ha="center", fontsize=11, fontweight="bold", color=BLUE)
ax.text(RX, 0.955, "INFORMAL", ha="center", fontsize=11, fontweight="bold", color=RED)

# core statement boxes
box(LX, 0.80, 0.34, 0.10, "#dbe6f0", BLUE, "Lean signature", "the declaration's type", BLUE)
box(RX, 0.80, 0.34, 0.10, "#f1ddd8", RED, "LaTeX statement", "the informal claim", RED)

# augmentation context trays (lighter tint)
box(LX, 0.60, 0.38, 0.13, "#eef3f8", BLUE,
    "+ packed dep context", "deps ranked by role · plumbing filtered", "#5b7fa6")
box(RX, 0.60, 0.38, 0.13, "#faf0ed", RED,
    "+ paragraph · abstract · deps", "informal context window", "#c07a6e")

# arrows into the judge
JY = 0.34
for x in (LX, RX):
    ax.add_patch(FancyArrowPatch((x, 0.535), (0.5, JY + 0.052),
                 arrowstyle="-|>", mutation_scale=13, lw=1.4, color=GRAY,
                 zorder=2, shrinkA=4, shrinkB=4,
                 connectionstyle="arc3,rad=0.0"))

# judge node
ax.add_patch(FancyBboxPatch((0.34, JY - 0.055), 0.32, 0.11,
             boxstyle="round,pad=0.006,rounding_size=0.03",
             facecolor="#ece6f2", edgecolor="#7e5b9e", linewidth=1.2, zorder=3))
ax.text(0.5, JY + 0.012, "JUDGE", ha="center", va="center", fontsize=11,
        fontweight="bold", color="#5d3f7e", zorder=4)
ax.text(0.5, JY - 0.026, "2× Opus 4.8 · symmetric context", ha="center",
        va="center", fontsize=8, color=GRAY, style="italic", zorder=4)

# verdict
ax.add_patch(FancyArrowPatch((0.5, JY - 0.058), (0.5, 0.165),
             arrowstyle="-|>", mutation_scale=14, lw=1.6, color=GRAY, zorder=2,
             shrinkA=2, shrinkB=2))
for x, word, col in ((0.36, "exact", GREEN), (0.5, "inexact", ORANGE),
                     (0.64, "wrong", WRONG)):
    ax.text(x, 0.115, word, ha="center", va="center", fontsize=10,
            fontweight="bold", color=col)
ax.text(0.5, 0.145, "verdict", ha="center", va="center", fontsize=8,
        color=GRAY, style="italic")

fig.text(0.5, 0.02,
         "The judge is grounded in the same dependency context that produced each "
         "statement's slogan — symmetric across both graphs.",
         ha="center", fontsize=9.5, color=GRAY, style="italic")
fig.savefig(f"{HERE}/figures/contextualized_judge.png", dpi=150, bbox_inches="tight")
print("wrote figures/contextualized_judge.png")
