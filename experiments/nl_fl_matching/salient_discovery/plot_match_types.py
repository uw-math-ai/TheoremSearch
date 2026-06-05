"""Three kinds of match in the Universal Graph -- three side-by-side panels.

Each panel illustrates ONE semantic-restatement match type with two pools and a
single arrow; the modalities are encoded by pool colour (formal = blue, informal
= green), so no single frame carries more than one arrow.

  panel 1  formal   <-> informal   formalization link        (amber)
           blue pool   green pool   -- ties Lean to literature
           § Bridging the Corpora

  panel 2  formal   <-> formal      cross-project twins       (purple)
           blue pool   blue pool    -- same result, two Lean projects
           § Cross-Project Twins

  panel 3  informal <-> informal    cross-paper restatement   (rust)
           green pool  green pool   -- same result, two papers
           § Literature Search in Context

Section names mirror the paper (graph-paper/sections/...). Labels in LaTeX
(mathtext CM). No numbers.

Output: data/match_types.png
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Ellipse, FancyArrowPatch, Circle

plt.rcParams["mathtext.fontset"] = "cm"

HERE = __file__.rsplit("/", 1)[0]

FORMAL    = "#3f72a0"
INFORMAL  = "#2a8f5a"
FORMAL_BG = "#e3ecf4"
INFORM_BG = "#e1f0e7"
INK       = "#222222"
GRAYREF   = "#7a7a7a"

# per-panel: (left_color, right_color, arrow_color, title,
#             left_label, right_label)
C_FI = "#d9821f"; C_FF = "#7e5b9e"; C_II = "#b5544b"
PANELS = [
    (FORMAL, INFORMAL, C_FI, r"$\mathrm{Formalization\ Link}$",
     r"$\mathbf{Formal}$", r"$\mathbf{Informal}$"),
    (FORMAL, FORMAL, C_FF, r"$\mathrm{Cross\text{-}Project\ Twins}$",
     r"$\mathrm{Project\ A}$", r"$\mathrm{Project\ B}$"),
    (INFORMAL, INFORMAL, C_II, r"$\mathrm{Cross\text{-}Paper\ Restatement}$",
     r"$\mathrm{Paper\ A}$", r"$\mathrm{Paper\ B}$"),
]

BG = {FORMAL: FORMAL_BG, INFORMAL: INFORM_BG}
LCX, RCX, CY = 0.275, 0.725, 0.52
BLOB_W, BLOB_H = 0.34, 0.52


def scatter_pool(rng, cx, anchor, n=9):
    """Scatter n nodes in the pool, with `anchor` forced as the first node
    (kept clear of the others so the match arrow reads as node-to-node)."""
    pts = [anchor]
    while len(pts) < n:
        t = rng.uniform(0, 2 * np.pi); r = np.sqrt(rng.uniform(0, 1)) * 0.86
        p = (cx + r * (BLOB_W / 2) * 0.82 * np.cos(t),
             CY + r * (BLOB_H / 2) * 0.82 * np.sin(t))
        if np.hypot(p[0] - anchor[0], p[1] - anchor[1]) < 0.07:
            continue
        pts.append(p)
    return pts


def draw_panel(ax, cfg, seed):
    lcol, rcol, acol, title, llab, rlab = cfg
    rng = np.random.default_rng(seed)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.set_aspect("equal"); ax.axis("off")

    # the two nodes the match arrow connects: inner-edge node of each pool,
    # drawn as Circle patches so the arrow can clip exactly to their edges.
    NODE_R = 0.021
    l_anchor = (LCX + 0.125, CY)
    r_anchor = (RCX - 0.125, CY)
    l_circ = Circle(l_anchor, NODE_R, facecolor=lcol, edgecolor="white",
                    linewidth=1.4, zorder=5)
    r_circ = Circle(r_anchor, NODE_R, facecolor=rcol, edgecolor="white",
                    linewidth=1.4, zorder=5)

    # pool blobs + scattered (non-anchor) nodes
    for cx, col, anchor in ((LCX, lcol, l_anchor), (RCX, rcol, r_anchor)):
        ax.add_patch(Ellipse((cx, CY), BLOB_W, BLOB_H, facecolor=BG[col],
                     edgecolor="none", zorder=0))
        pts = scatter_pool(rng, cx, anchor)[1:]   # drop anchor; drawn as Circle
        xs, ys = zip(*pts)
        ax.scatter(xs, ys, s=rng.uniform(60, 130, size=len(pts)), color=col,
                   edgecolor="white", linewidth=1.0, zorder=3, alpha=0.95)
    ax.add_patch(l_circ); ax.add_patch(r_circ)

    # match arrow: clips exactly to each anchor circle's boundary (no gap)
    ax.add_patch(FancyArrowPatch(l_anchor, r_anchor, arrowstyle="<|-|>",
                 mutation_scale=14, lw=2.6, color=acol, zorder=4,
                 shrinkA=0, shrinkB=0, patchA=l_circ, patchB=r_circ))

    # panel title (colour of the arrow)
    ax.text(0.5, 0.93, title, ha="center", va="center", fontsize=13,
            color=acol, fontweight="bold")
    # pool identity labels
    ax.text(LCX, 0.115, llab, ha="center", va="center", fontsize=11.5, color=lcol)
    ax.text(RCX, 0.115, rlab, ha="center", va="center", fontsize=11.5, color=rcol)


fig, axes = plt.subplots(1, 3, figsize=(12.4, 4.2))
for ax, cfg, seed in zip(axes, PANELS, (5, 11, 23)):
    draw_panel(ax, cfg, seed)

# shared key (figure bottom)
kax = fig.add_axes((0.30, 0.005, 0.40, 0.07)); kax.axis("off")
kax.set_xlim(0, 1); kax.set_ylim(0, 1)
kax.scatter([0.10], [0.5], s=130, color=FORMAL, edgecolor="white", linewidth=1)
kax.text(0.135, 0.5, r"$\mathrm{Formal\ (Lean)}$", ha="left", va="center",
         fontsize=10, color="#444")
kax.scatter([0.56], [0.5], s=130, color=INFORMAL, edgecolor="white", linewidth=1)
kax.text(0.595, 0.5, r"$\mathrm{Informal\ (arXiv\,/\,LaTeX)}$", ha="left",
         va="center", fontsize=10, color="#444")

fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.10, wspace=0.04)
fig.savefig(f"{HERE}/figures/match_types.png", dpi=150, bbox_inches="tight")
print("wrote figures/match_types.png")
