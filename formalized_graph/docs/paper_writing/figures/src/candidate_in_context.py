"""Candidate-in-context: 3D macro view of the NL <-> FL corpus, two panels.

Two side-by-side 3D scenes share palette, geometry, and legend. Per the
LaTeX-first text policy in figure_style.md, all prose lives in the
caption — the figure itself carries only data-identifying plane labels,
the encoding legend, and direct labels on the spotlit gold candidate and
its named premises. The k=1 / k=2 distinction is panel-encoded via tiny
"(a)" / "(b)" corner labels for cross-reference from the caption.

Each panel:
  * top plane (red)     = informal dependency graph
  * bottom plane (blue) = formal dependency graph
  * gold node           = the candidate (an UNFORMALIZED target)
  * filled red nodes    = formalized informal neighbors
  * outlined red nodes  = unformalized informal neighbors
  * blue nodes (bottom) = formal Lean decls
  * green dashed vert.  = blueprint \\lean{...} matches

The spotlit cluster (gold + k=1 neighbors) is hand-pinned at the centre
of each plane and pushed radially outward from the gold node by ~35%
relative to the previous layout, with an enlarged background-free buffer
ring so the locality of the embedding-based retrieval reads visually.
Background graphs are synthetic clustered Gaussians (replace with real
PCA before paper submission). Seed is fixed (seed=7) for reproducibility.

Build:  python candidate_in_context.py
Output: ../out/candidate_in_context.{pdf,png}

Paper integration:
  \\begin{figure}[t]
    \\centering
    \\includegraphics[width=\\linewidth]{figures/out/candidate_in_context.pdf}
    \\caption{Macro view of a candidate formalization target (gold) and
             its k=1 reach (saturated) vs. k=2 reach (faded) across the
             dual-plane informal/formal dependency graphs. Background
             nodes are the surrounding corpus scaled to ~60+55 nodes per
             plane; node area is constant within plane. Panel (a): k=1
             reach. Panel (b): k=2 reach. The empty buffer between the
             spotlit cluster and the corpus illustrates the locality of
             the embedding-based retrieval.}
    \\label{fig:candidate-in-context}
  \\end{figure}
"""

from __future__ import annotations
from pathlib import Path

import numpy as np
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401  (registers '3d' projection)
from mpl_toolkits.mplot3d import proj3d
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

# ---- Palette (figure_style.md §2 — gold added) --------------------------
PAL = {
    "blue_primary":  "#2E5C8A",
    "accent_red":    "#C8553D",
    "accent_green":  "#5B8C5A",
    "accent_gold":   "#C9A227",   # candidate (unformalized target)
    "gold_dark":     "#8C7019",
    "gray_text":     "#2A2A2A",
    "gray_rule":     "#999999",
}

mpl.rcParams.update({
    "font.family":        "sans-serif",
    "font.sans-serif":    ["Helvetica", "Arial", "DejaVu Sans"],
    "font.size":          9,
    "pdf.fonttype":       42,
    "ps.fonttype":        42,
    "savefig.bbox":       "tight",
    "savefig.pad_inches": 0.04,
})

# =========================================================================
# Geometry constants
# =========================================================================
PLANE_W           = 10.0
N_CLUSTERS        = 3
N_NL              = 16
N_FL              = 13
# Buffer ring: HIGHLIGHT_RADIUS is enlarged so that background nodes stay a
# visible empty annulus away from the k=1 ring (which itself was pushed
# outward by ~35%). The spotlit cluster's locality is what sells the figure.
HIGHLIGHT_RADIUS  = 3.7   # was 2.8; +32% → empty buffer beyond k=1 ring
Z_TOP, Z_BOT      = 4.0, 0.0

CENTER    = np.array([PLANE_W / 2, PLANE_W / 2])
K1_ANGLES = [40, 130, 215, 305]   # degrees — 4 k=1 neighbors around candidate
K1_RADIUS = 2.05   # was 1.5; k=1 neighbors pushed +37% outward from gold
FL_RADIUS = 2.15   # was 1.6; matched outward shove on the formal plane

LABEL_BBOX = dict(facecolor="white", edgecolor=PAL["gray_rule"],
                  linewidth=0.4, boxstyle="round,pad=0.24", alpha=0.95)


class Arrow3D(FancyArrowPatch):
    """Thin leader line that respects 3D projection."""
    def __init__(self, xs, ys, zs, *args, **kwargs):
        super().__init__((0, 0), (0, 0), *args, **kwargs)
        self._verts3d = xs, ys, zs

    def do_3d_projection(self, renderer=None):
        xs3d, ys3d, zs3d = self._verts3d
        xs, ys, _ = proj3d.proj_transform(xs3d, ys3d, zs3d, self.axes.M)
        self.set_positions((xs[0], ys[0]), (xs[1], ys[1]))
        return float(np.min(zs3d))


# =========================================================================
# Synthetic background data (one realisation reused for both panels)
# =========================================================================
def make_background(seed: int) -> tuple[np.ndarray, np.ndarray,
                                        list[tuple[int, int]],
                                        list[tuple[int, int]],
                                        dict[int, int]]:
    rng     = np.random.default_rng(seed)
    centers = rng.uniform(1.8, PLANE_W - 1.8, size=(N_CLUSTERS, 2))

    def layer(n: int, jitter: float) -> tuple[np.ndarray, np.ndarray]:
        pts: list[np.ndarray] = []
        cl: list[int]         = []
        while len(pts) < n:
            cid = int(rng.integers(0, N_CLUSTERS))
            p   = np.clip(centers[cid] + rng.normal(0, jitter, size=2),
                          0.4, PLANE_W - 0.4)
            if np.linalg.norm(p - CENTER) < HIGHLIGHT_RADIUS:
                continue
            pts.append(p); cl.append(cid)
        return np.array(pts), np.array(cl)

    nl_xy, nl_cl = layer(N_NL, jitter=1.4)
    fl_xy, fl_cl = layer(N_FL, jitter=1.5)

    def knn_edges(xy: np.ndarray, cl: np.ndarray, k: int) -> list[tuple[int, int]]:
        edges: set[tuple[int, int]] = set()
        for i in range(len(xy)):
            same = np.where(cl == cl[i])[0]
            same = same[same != i]
            if len(same) == 0:
                continue
            d = np.linalg.norm(xy[same] - xy[i], axis=1)
            for j in same[np.argsort(d)[:k]]:
                edges.add((min(i, int(j)), max(i, int(j))))
        return list(edges)

    nl_edges = knn_edges(nl_xy, nl_cl, k=2)
    fl_edges = knn_edges(fl_xy, fl_cl, k=2)

    dmat    = np.linalg.norm(nl_xy[:, None] - fl_xy[None, :], axis=2)
    nearest = dmat.argmin(axis=1)
    match: dict[int, int] = {}
    for i in range(N_NL):
        if dmat[i, nearest[i]] < 1.5:
            match[i] = int(nearest[i])
    return nl_xy, fl_xy, nl_edges, fl_edges, match


# =========================================================================
# Panel scenes
# =========================================================================
def setup_axes(ax) -> None:
    ax.view_init(elev=22, azim=-58)
    ax.set_xlim(-0.2, PLANE_W + 0.2)
    ax.set_ylim(-0.2, PLANE_W + 0.2)
    ax.set_zlim(-0.4, 4.7)
    ax.set_box_aspect((PLANE_W, PLANE_W, 4.7), zoom=1.05)
    ax.set_axis_off()
    for a in (ax.xaxis, ax.yaxis, ax.zaxis):
        a.pane.fill = False
        a.pane.set_edgecolor((1, 1, 1, 0))
        a.line.set_color((1, 1, 1, 0))


def draw_background(ax, nl_xy, fl_xy, nl_edges, fl_edges, match) -> None:
    # Planes
    for z, color in [(Z_TOP, PAL["accent_red"]),
                     (Z_BOT, PAL["blue_primary"])]:
        corners = [[(0, 0, z), (PLANE_W, 0, z),
                    (PLANE_W, PLANE_W, z), (0, PLANE_W, z)]]
        ax.add_collection3d(Poly3DCollection(
            corners, facecolor=color, alpha=0.05,
            edgecolor=color, linewidth=0.5))

    # Edges
    for i, j in nl_edges:
        ax.plot([nl_xy[i, 0], nl_xy[j, 0]],
                [nl_xy[i, 1], nl_xy[j, 1]], [Z_TOP, Z_TOP],
                color=PAL["accent_red"], alpha=0.20, lw=0.45)
    for i, j in fl_edges:
        ax.plot([fl_xy[i, 0], fl_xy[j, 0]],
                [fl_xy[i, 1], fl_xy[j, 1]], [Z_BOT, Z_BOT],
                color=PAL["blue_primary"], alpha=0.20, lw=0.45)
    for nl, fl in match.items():
        ax.plot([nl_xy[nl, 0], fl_xy[fl, 0]],
                [nl_xy[nl, 1], fl_xy[fl, 1]], [Z_TOP, Z_BOT],
                color=PAL["accent_green"], alpha=0.12, lw=0.35,
                linestyle=(0, (2, 2)))

    # Nodes
    ax.scatter(nl_xy[:, 0], nl_xy[:, 1], [Z_TOP] * len(nl_xy),
               c=PAL["accent_red"], s=28, alpha=0.45, edgecolor="none",
               depthshade=False)
    ax.scatter(fl_xy[:, 0], fl_xy[:, 1], [Z_BOT] * len(fl_xy),
               c=PAL["blue_primary"], s=28, alpha=0.45, edgecolor="none",
               depthshade=False)


def draw_candidate(ax) -> np.ndarray:
    """Gold candidate at plane center."""
    cand = CENTER.copy()
    ax.scatter([cand[0]], [cand[1]], [Z_TOP],
               c=PAL["accent_gold"], s=300,
               edgecolor=PAL["gold_dark"], linewidth=1.8,
               zorder=10, depthshade=False)
    return cand


def k1_position(angle_deg: float, radius: float = K1_RADIUS) -> np.ndarray:
    return CENTER + radius * np.array([np.cos(np.radians(angle_deg)),
                                       np.sin(np.radians(angle_deg))])


def draw_panel_k1(ax, bg) -> None:
    """Scenario A: candidate has formalized k=1 neighbors (graph pack hangs
    directly below)."""
    nl_xy, fl_xy, nl_edges, fl_edges, match = bg
    draw_background(ax, nl_xy, fl_xy, nl_edges, fl_edges, match)
    cand = draw_candidate(ax)

    k1_pos = np.array([k1_position(a) for a in K1_ANGLES])
    form_idx, unform_idx = [0, 1, 3], [2]

    # FL pack: corresponding angular spread, same plane center
    rng = np.random.default_rng(11)
    fl_pack = np.array([
        CENTER + FL_RADIUS * np.array([np.cos(np.radians(K1_ANGLES[i] + 12)),
                                       np.sin(np.radians(K1_ANGLES[i] + 12))])
        + rng.normal(0, 0.15, size=2)
        for i in form_idx
    ])

    # Fan-out edges
    for kpos in k1_pos:
        ax.plot([cand[0], kpos[0]], [cand[1], kpos[1]], [Z_TOP, Z_TOP],
                color=PAL["accent_red"], alpha=0.95, lw=1.2)

    # Vertical blueprint links (formalized k=1 only)
    for k_idx, fl_pos in zip(form_idx, fl_pack):
        kp = k1_pos[k_idx]
        ax.plot([kp[0], fl_pos[0]], [kp[1], fl_pos[1]], [Z_TOP, Z_BOT],
                color=PAL["accent_green"], alpha=0.95, lw=1.2,
                linestyle=(0, (3.5, 1.5)))

    # FL pack internal edges
    for i in range(len(fl_pack)):
        for j in range(i + 1, len(fl_pack)):
            ax.plot([fl_pack[i, 0], fl_pack[j, 0]],
                    [fl_pack[i, 1], fl_pack[j, 1]], [Z_BOT, Z_BOT],
                    color=PAL["blue_primary"], alpha=0.55, lw=0.9)

    # k=1 nodes
    for i in form_idx:
        ax.scatter([k1_pos[i, 0]], [k1_pos[i, 1]], [Z_TOP],
                   c=PAL["accent_red"], s=95, edgecolor=PAL["accent_red"],
                   linewidth=0.6, zorder=10, depthshade=False)
    for i in unform_idx:
        ax.scatter([k1_pos[i, 0]], [k1_pos[i, 1]], [Z_TOP],
                   c="white", s=95, edgecolor=PAL["accent_red"], linewidth=1.6,
                   zorder=10, depthshade=False)

    # FL pack nodes
    for fp in fl_pack:
        ax.scatter([fp[0]], [fp[1]], [Z_BOT],
                   c=PAL["blue_primary"], s=95, edgecolor=PAL["blue_primary"],
                   linewidth=0.6, zorder=10, depthshade=False)

    # Candidate label (leader line to upper-left)
    ax.add_artist(Arrow3D([cand[0], cand[0] - 2.7], [cand[1], cand[1] + 3.1],
                          [Z_TOP, Z_TOP + 1.1],
                          arrowstyle="-", color=PAL["gold_dark"],
                          lw=0.6, alpha=0.7, zorder=14))
    ax.text(cand[0] - 2.8, cand[1] + 3.1, Z_TOP + 1.1,
            "candidate\n(unformalized)",
            fontsize=7.6, color=PAL["gold_dark"], weight="bold",
            ha="right", va="bottom", zorder=15, bbox=LABEL_BBOX)

    # Two FL premise labels — pick widest x-separation
    if len(fl_pack) >= 2:
        leftmost  = int(fl_pack[:, 0].argmin())
        rightmost = int(fl_pack[:, 0].argmax())
        for idx, name, side in [(leftmost,  "IsCadlag",            "right"),
                                (rightmost, "Martingale.classDL",  "left")]:
            p  = fl_pack[idx]
            dx = -0.5 if side == "right" else 0.5
            ha = "right" if side == "right" else "left"
            ax.text(p[0] + dx, p[1] - 0.7, Z_BOT - 0.05,
                    name, fontsize=7.0, color=PAL["blue_primary"],
                    family="monospace", ha=ha, va="center",
                    zorder=15, bbox=LABEL_BBOX)


def draw_panel_k2(ax, bg) -> None:
    """Scenario B: every k=1 neighbor is unformalized; closest formalization
    is one of the k=1 neighbor's neighbors (k=2 from the candidate)."""
    nl_xy, fl_xy, nl_edges, fl_edges, match = bg
    draw_background(ax, nl_xy, fl_xy, nl_edges, fl_edges, match)
    cand = draw_candidate(ax)

    k1_pos = np.array([k1_position(a) for a in K1_ANGLES])

    # One k=1 neighbor (idx=1, top-left) has a k=2 child that IS formalized.
    K2_PARENT  = 1
    parent_ang = K1_ANGLES[K2_PARENT]
    # k=2 sits one hop beyond k=1; keep it inside HIGHLIGHT_RADIUS so the
    # buffer ring still reads as empty background-free space.
    k2_pos = CENTER + (K1_RADIUS + 1.3) * np.array(
        [np.cos(np.radians(parent_ang + 8)),
         np.sin(np.radians(parent_ang + 8))]
    )
    fl_k2 = k2_pos + np.array([0.55, -0.15])      # rough projection below k=2

    # Fan-out edges from candidate to k=1
    for kpos in k1_pos:
        ax.plot([cand[0], kpos[0]], [cand[1], kpos[1]], [Z_TOP, Z_TOP],
                color=PAL["accent_red"], alpha=0.95, lw=1.2)

    # Extra red edge: k=1 (parent) -> k=2 (formalized child)
    parent = k1_pos[K2_PARENT]
    ax.plot([parent[0], k2_pos[0]], [parent[1], k2_pos[1]], [Z_TOP, Z_TOP],
            color=PAL["accent_red"], alpha=0.95, lw=1.2)

    # Vertical blueprint link from k=2 down to FL
    ax.plot([k2_pos[0], fl_k2[0]], [k2_pos[1], fl_k2[1]], [Z_TOP, Z_BOT],
            color=PAL["accent_green"], alpha=0.95, lw=1.2,
            linestyle=(0, (3.5, 1.5)))

    # k=1 nodes (all unformalized)
    for i in range(4):
        ax.scatter([k1_pos[i, 0]], [k1_pos[i, 1]], [Z_TOP],
                   c="white", s=95, edgecolor=PAL["accent_red"], linewidth=1.6,
                   zorder=10, depthshade=False)

    # k=2 node (formalized, filled red)
    ax.scatter([k2_pos[0]], [k2_pos[1]], [Z_TOP],
               c=PAL["accent_red"], s=95, edgecolor=PAL["accent_red"],
               linewidth=0.6, zorder=10, depthshade=False)

    # Single FL node
    ax.scatter([fl_k2[0]], [fl_k2[1]], [Z_BOT],
               c=PAL["blue_primary"], s=95, edgecolor=PAL["blue_primary"],
               linewidth=0.6, zorder=10, depthshade=False)

    # Candidate label
    ax.add_artist(Arrow3D([cand[0], cand[0] - 2.7], [cand[1], cand[1] + 3.1],
                          [Z_TOP, Z_TOP + 1.1],
                          arrowstyle="-", color=PAL["gold_dark"],
                          lw=0.6, alpha=0.7, zorder=14))
    ax.text(cand[0] - 2.8, cand[1] + 3.1, Z_TOP + 1.1,
            "candidate\n(unformalized)",
            fontsize=7.6, color=PAL["gold_dark"], weight="bold",
            ha="right", va="bottom", zorder=15, bbox=LABEL_BBOX)

    # FL premise label
    ax.text(fl_k2[0] + 0.5, fl_k2[1] - 0.7, Z_BOT - 0.05,
            "Martingale.classDL", fontsize=7.0,
            color=PAL["blue_primary"], family="monospace",
            ha="left", va="center", zorder=15, bbox=LABEL_BBOX)


# =========================================================================
# Figure
# =========================================================================
bg = make_background(seed=7)

fig = plt.figure(figsize=(12.2, 5.6))
ax_a = fig.add_subplot(1, 2, 1, projection="3d")
ax_b = fig.add_subplot(1, 2, 2, projection="3d")
for ax in (ax_a, ax_b):
    setup_axes(ax)

draw_panel_k1(ax_a, bg)
draw_panel_k2(ax_b, bg)

# ---- Plane labels (data-identifying only — one word per plane,         --
#       horizontally centred over each panel; informal=red, formal=blue --
#       per figure_style.md §11 dual-plane convention). -----------------
for ax in (ax_a, ax_b):
    ax.text2D(0.5, 0.965, "informal",
              transform=ax.transAxes,
              color=PAL["accent_red"], fontsize=10.5,
              weight="bold", ha="center", va="top")
    ax.text2D(0.5, 0.035, "formal",
              transform=ax.transAxes,
              color=PAL["blue_primary"], fontsize=10.5,
              weight="bold", ha="center", va="bottom")

# ---- Panel id labels (cross-ref from caption only — no prose) ----------
for ax, tag in ((ax_a, "(a)"), (ax_b, "(b)")):
    ax.text2D(0.03, 0.965, tag,
              transform=ax.transAxes,
              color=PAL["gray_text"], fontsize=10.5,
              weight="bold", ha="left", va="top")

# ---- Shared legend (top-right, framed) ---------------------------------
lax = fig.add_axes((0.875, 0.755, 0.115, 0.225))
lax.set_xlim(0, 1); lax.set_ylim(0, 1)
lax.set_xticks([]); lax.set_yticks([])
for spine in lax.spines.values():
    spine.set_edgecolor(PAL["gray_rule"])
    spine.set_linewidth(0.5)
lax.set_facecolor("white")

ys = [0.86, 0.68, 0.50, 0.32, 0.14]
# Candidate (gold)
lax.scatter([0.13], [ys[0]], c=PAL["accent_gold"], s=68,
            edgecolor=PAL["gold_dark"], linewidth=1.0)
lax.text(0.28, ys[0], "candidate", fontsize=7.5, color=PAL["gray_text"], va="center")
# Filled red NL
lax.scatter([0.13], [ys[1]], c=PAL["accent_red"], s=44,
            edgecolor=PAL["accent_red"], linewidth=0.6)
lax.text(0.28, ys[1], "formalized NL", fontsize=7.5, color=PAL["gray_text"], va="center")
# Outlined NL
lax.scatter([0.13], [ys[2]], c="white", s=44,
            edgecolor=PAL["accent_red"], linewidth=1.4)
lax.text(0.28, ys[2], "unformalized NL", fontsize=7.5, color=PAL["gray_text"], va="center")
# Filled FL
lax.scatter([0.13], [ys[3]], c=PAL["blue_primary"], s=44,
            edgecolor=PAL["blue_primary"], linewidth=0.6)
lax.text(0.28, ys[3], "formal Lean decl", fontsize=7.5, color=PAL["gray_text"], va="center")
# Dashed line
lax.plot([0.05, 0.21], [ys[4], ys[4]],
         color=PAL["accent_green"], lw=1.2, ls=(0, (3.5, 1.5)))
lax.text(0.28, ys[4], "Blueprint match", fontsize=7.5, color=PAL["gray_text"], va="center")

# =========================================================================
# Save
# =========================================================================
out_dir = Path(__file__).resolve().parents[1] / "out"
out_dir.mkdir(parents=True, exist_ok=True)
out_pdf = out_dir / "candidate_in_context.pdf"
out_png = out_dir / "candidate_in_context.png"
fig.savefig(out_pdf, format="pdf")
fig.savefig(out_png, format="png", dpi=300)
print(f"wrote {out_pdf}")
print(f"wrote {out_png}")
