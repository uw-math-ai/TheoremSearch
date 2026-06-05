"""V4 -- Restatement multiplicity histogram (one-to-many as a number).

Distribution of how many confirmed informal restatements each formal theorem
has in its top-5. Most matched theorems have exactly one; a meaningful tail
has several.

MOCK DATA -- replace counts with the Arm-C per-node tally of edge=True among
top-5. Mirrors the blueprint finding (one informal -> up to 16 formals) from
the reverse direction.

Output: data/multiplicity_hist.png
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BLUE = "#3f72a0"; INK = "#222222"; GRAY = "#666666"
HERE = __file__.rsplit("/", 1)[0]

# confirmed matches in top-5 -> number of formal nodes (illustrative)
X = [1, 2, 3, 4, 5]
COUNTS = [3810, 624, 188, 61, 23]

fig, ax = plt.subplots(figsize=(7.4, 4.2))
bars = ax.bar(X, COUNTS, width=0.66, color=BLUE, zorder=3)
# darken the multi-match tail to mark it
for b, x in zip(bars, X):
    if x >= 2:
        b.set_color("#2f5a80")

# value labels on top
for x, c in zip(X, COUNTS):
    ax.text(x, c + max(COUNTS) * 0.015, f"{c:,}", ha="center", va="bottom",
            fontsize=9, color=INK)

ax.set_xticks(X)
ax.set_xlabel("confirmed informal restatements in top-5", fontsize=10, color=INK)
ax.set_ylabel("formal theorems", fontsize=10, color=INK)
ax.set_ylim(0, max(COUNTS) * 1.12)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
ax.spines["left"].set_color(GRAY); ax.spines["bottom"].set_color(GRAY)
ax.tick_params(colors=GRAY)

# annotate the tail (arrow stays clear of the value labels)
ax.annotate("multi-restatement tail", xy=(3.9, 110), xytext=(2.75, 1300),
            fontsize=9.5, color="#2f5a80", style="italic", ha="left",
            arrowprops=dict(arrowstyle="-|>", color="#2f5a80", lw=1.2))

fig.text(0.5, 0.005,
         "Most matched theorems have exactly one restatement; a meaningful tail "
         "re-states the same result across several papers.",
         ha="center", fontsize=9, color=GRAY, style="italic")
fig.tight_layout(rect=(0, 0.04, 1, 1))
fig.savefig(f"{HERE}/figures/multiplicity_hist.png", dpi=150, bbox_inches="tight")
print("wrote figures/multiplicity_hist.png")
