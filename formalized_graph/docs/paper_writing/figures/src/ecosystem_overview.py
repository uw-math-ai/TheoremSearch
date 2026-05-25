"""Ecosystem overview: Mathlib at the center, project repos as a ring of circles.

Three encodings per project circle, plus a top-5 NL annotation:
  * area    ~ statement count          (radius ~ n ** 0.42)
  * overlap ~ fraction of the project's outgoing formal_dependency edges
              that target Mathlib   (NEW: see "overlap metric" note below)
  * opacity ~ NL-graph mutual-rank-1 link strength, anchored to project
              (linearly normalised to alpha in [0.25, 1.0])
  * gold ring (ACCENT_GOLD, 1.5pt) around the top 5 projects by mutual
              rank-1 NL link count.

Overlap metric (changed 2026-05-25):
    Previously this was "fraction of project decls that have >=1 Mathlib
    citation". That metric saturates -- 11/24 projects had cite_pct = 1.0
    and most others were >=0.95, so every project sat ~flush onto Mathlib.

    The new metric is per-EDGE rather than per-DECL:
        frac_mathlib_edges = (# outgoing formal_dependency edges into
                              Mathlib) / (# outgoing edges total)
    A self-contained project with many internal edges (pfr, FLT) gets a
    lower value; a small project that just wraps a couple of Mathlib
    lemmas gets a value near 1. Observed range across the 24 projects is
    documented in the run log printed at the bottom of this script.

Visual mapping (size-independent, 2026-05-25 rev):
    The previous rule scaled the inward push by (R_mathlib + R_proj),
    which made small circles look "barely touching" and large ones look
    "swallowed" even at the same overlap fraction. The new rule encodes
    "fraction of THIS project's circle inside Mathlib" directly:

        d_i = R_mathlib + R_proj_i * (1 - 2 * m_i)

    so the visible nestedness is governed only by m_i, not by R_proj_i.
    Properties:
      m=0   -> external tangent (d = R_M + R_p)
      m=0.5 -> project center exactly on Mathlib's rim (half inside)
      m=1   -> fully nested (d = R_M - R_p)

    We map the raw frac_mathlib_edges metric (observed ~ [0.68, 0.96])
    linearly into m in [0.2, 0.7] so nothing is fully outside or fully
    nested -- every project stays legible.

Output:
  ../out/ecosystem_overview.pdf
  ../out/ecosystem_overview.png
"""

from __future__ import annotations
import json
import math
from pathlib import Path

import numpy as np
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import Circle

# ---- Palette (figure_style.md s2) ---------------------------------------
PAL = {
    "blue_primary":  "#2E5C8A",
    "blue_soft":     "#A8C5E0",
    "gray_text":     "#2A2A2A",
    "gray_rule":     "#999999",
    "accent_purple": "#7E5B9E",
    "accent_gold":   "#C9A227",
    "gold_dark":     "#8C7019",
}

mpl.rcParams.update({
    "font.family":        "sans-serif",
    "font.sans-serif":    ["Helvetica", "Arial", "DejaVu Sans"],
    "font.size":          9,
    "axes.titlesize":     10,
    "axes.labelsize":     9,
    "xtick.labelsize":    8,
    "ytick.labelsize":    8,
    "legend.fontsize":    9,
    "legend.frameon":     False,
    "axes.edgecolor":     PAL["gray_rule"],
    "axes.linewidth":     0.8,
    "pdf.fonttype":       42,
    "ps.fonttype":        42,
    "savefig.bbox":       "tight",
    "savefig.pad_inches": 0.04,
})

LABEL_BBOX = dict(facecolor="white", edgecolor=PAL["gray_rule"],
                  linewidth=0.4, boxstyle="round,pad=0.22", alpha=0.95)

# =========================================================================
# Load data
# =========================================================================
DATA_PATH = Path("/tmp/ecosystem_data.json")
with DATA_PATH.open() as f:
    DATA = json.load(f)

mathlib_total = DATA["mathlib_total"]
projects = DATA["projects"]   # list of dicts incl. frac_mathlib_edges, nl_link_count

# =========================================================================
# Encodings
# =========================================================================
# Radius: between sqrt and log (exp=0.42). See prior rev for rationale.
RADIUS_EXP = 0.42
R_MATHLIB_TARGET = 2.0
k_radius = R_MATHLIB_TARGET / (mathlib_total ** RADIUS_EXP)

def radius_of(n: int) -> float:
    return k_radius * (n ** RADIUS_EXP)

R_mathlib = radius_of(mathlib_total)

# ---- Overlap (new metric) -----------------------------------------------
# Print the observed distribution for the run log + script-doc comment.
edge_fracs = sorted(p["frac_mathlib_edges"] for p in projects)
print("overlap metric: fraction of outgoing dependency edges that target Mathlib")
print(f"  range observed [{edge_fracs[0]:.3f}, {edge_fracs[-1]:.3f}]"
      f"   median {edge_fracs[len(edge_fracs) // 2]:.3f}")
for p in sorted(projects, key=lambda d: d["frac_mathlib_edges"]):
    print(f"    {p['project']:40s} frac={p['frac_mathlib_edges']:.3f}"
          f"  edges={p['n_outgoing_edges']:>8,}  stmts={p['statements']:>6,}")

# Normalise frac_mathlib_edges to m in [M_LO, M_HI]. The geometric rule
# below uses m as "fraction of project area inside Mathlib" (heuristic):
#   d_i = R_mathlib + R_proj_i * (1 - 2 * m_i)
# We avoid m=0 (fully outside) and m=1 (fully nested) so every project
# stays visually distinguishable.
M_LO, M_HI = 0.20, 0.70
f_lo = min(edge_fracs)
f_hi = max(edge_fracs)
def overlap_m(frac: float) -> float:
    if f_hi <= f_lo:
        return 0.5 * (M_LO + M_HI)
    t = (frac - f_lo) / (f_hi - f_lo)         # raw -> [0, 1]
    return M_LO + t * (M_HI - M_LO)           # -> [M_LO, M_HI]

print(f"overlap mapping: raw [{f_lo:.3f}, {f_hi:.3f}] -> m [{M_LO}, {M_HI}]")

# Opacity from NL link count.
nl_counts = np.array([p["nl_link_count"] for p in projects], dtype=float)
nl_max = nl_counts.max() if nl_counts.max() > 0 else 1.0
def alpha_of(n_links: int) -> float:
    return 0.25 + 0.75 * (n_links / nl_max)

# ---- Top 5 NL-linked (gold-ring set) ------------------------------------
top5_nl = sorted(projects, key=lambda p: -p["nl_link_count"])[:5]
top5_set = {p["project"] for p in top5_nl}
print("top 5 NL-linked projects (gold ring):")
for p in top5_nl:
    print(f"    {p['project']:40s} nl_links={p['nl_link_count']}")

# =========================================================================
# Layout: arrange project circles around Mathlib center
# =========================================================================
N = len(projects)
angles = np.linspace(0, 2 * np.pi, N, endpoint=False)
# Rotate so largest project sits up-right for label space.
angles = angles + np.radians(-65)

centers = []
m_log = []
for p, theta in zip(projects, angles):
    R_p = radius_of(p["statements"])
    m = overlap_m(p["frac_mathlib_edges"])
    # Size-independent geometric rule: center distance only depends on
    # the project's own radius and m. The visible "fraction of this
    # project inside Mathlib" reads consistently across sizes.
    d = R_mathlib + R_p * (1.0 - 2.0 * m)
    cx = d * math.cos(theta)
    cy = d * math.sin(theta)
    centers.append((cx, cy, R_p, m))
    m_log.append((p["project"], p["frac_mathlib_edges"], m))

print("per-project m (sorted):")
for name, raw, m in sorted(m_log, key=lambda x: x[2]):
    print(f"    {name:40s} raw={raw:.3f}  m={m:.3f}")

max_extent = max(max(abs(c[0]) + c[2], abs(c[1]) + c[2]) for c in centers)
PAD = 1.6
LIM = max(max_extent + PAD, R_mathlib + PAD)

# =========================================================================
# Draw
# =========================================================================
fig, ax = plt.subplots(figsize=(7.0, 7.0))
ax.set_aspect("equal")
ax.set_xlim(-LIM, LIM)
ax.set_ylim(-LIM, LIM)
ax.set_axis_off()

# Mathlib (low alpha fill, solid edge)
ax.add_patch(Circle((0, 0), R_mathlib,
                    facecolor=PAL["blue_primary"], alpha=0.18,
                    edgecolor=PAL["blue_primary"], linewidth=1.0, zorder=2))
ax.text(0, 0, "Mathlib",
        fontsize=14, weight="bold", color=PAL["blue_primary"],
        ha="center", va="center", zorder=20,
        bbox=dict(facecolor="white", edgecolor="none",
                  boxstyle="round,pad=0.20", alpha=0.85))
ax.text(0, -0.32, f"{mathlib_total:,} decls",
        fontsize=8, color=PAL["gray_text"], ha="center", va="top",
        zorder=20)

# Project circles
for (cx, cy, R_p, t), p in zip(centers, projects):
    a = alpha_of(p["nl_link_count"])
    ax.add_patch(Circle((cx, cy), R_p,
                        facecolor=PAL["accent_purple"], alpha=a,
                        edgecolor=PAL["accent_purple"], linewidth=1.0,
                        zorder=3))
    # Gold ring around top-5 NL-linked projects.
    if p["project"] in top5_set:
        # Stroked just outside the circle so the purple edge stays visible.
        ring_r = R_p + 0.045 * LIM * 0.10  # tiny outward offset, scale-aware
        ax.add_patch(Circle((cx, cy), R_p + 0.012 * LIM,
                            facecolor="none",
                            edgecolor=PAL["accent_gold"],
                            linewidth=1.5,
                            zorder=4))

# =========================================================================
# Labels: ONLY the top-5 NL projects (per task spec)
# =========================================================================
# Collect (angle, p, center) for the labelled set, sort by angle, and bump
# any pair whose angular separation is small (e.g. adjacent in the ring)
# further out so the bbox'd labels don't overlap.
labelled_set = set(top5_set)
to_label = []
for (cx, cy, R_p, t), p in zip(centers, projects):
    if p["project"] in labelled_set:
        to_label.append((math.atan2(cy, cx), cx, cy, R_p, p))
to_label.sort(key=lambda x: x[0])

# Per-label radial offset; default 0.65, bumped if neighbour is too close.
MIN_SEP = math.radians(360 / len(projects) * 1.3)  # ~ one+ slot apart
extras = [0.65] * len(to_label)
for i in range(len(to_label)):
    j = (i + 1) % len(to_label)
    a_i, a_j = to_label[i][0], to_label[j][0]
    sep = (a_j - a_i) % (2 * math.pi)
    if sep < MIN_SEP:
        # push one of the two labels (the smaller-NL one) further out
        ni = to_label[i][4]["nl_link_count"]
        nj = to_label[j][4]["nl_link_count"]
        push = i if ni <= nj else j
        extras[push] = 1.45

for (theta, cx, cy, R_p, p), label_radius_extra in zip(to_label, extras):
    ax_pt = (cx + R_p * math.cos(theta), cy + R_p * math.sin(theta))
    lx = cx + (R_p + label_radius_extra) * math.cos(theta)
    ly = cy + (R_p + label_radius_extra) * math.sin(theta)
    ha = "left"   if math.cos(theta) > 0.10 else ("right" if math.cos(theta) < -0.10 else "center")
    va = "bottom" if math.sin(theta) > 0.10 else ("top"   if math.sin(theta) < -0.10 else "center")
    ax.plot([ax_pt[0], lx], [ax_pt[1], ly],
            color=PAL["gray_rule"], lw=0.5, alpha=0.6, zorder=19)
    ax.text(lx, ly, p["project"],
            fontsize=8,
            color=PAL["gold_dark"], weight="bold",
            ha=ha, va=va, zorder=21, bbox=LABEL_BBOX)

# =========================================================================
# Encoding legend -- top-right corner, with subtle white bbox padding behind
# each row so the legend reads as a self-contained block separate from the
# Mathlib blob / project labels. Moved from top-left to top-right (emptier
# quadrant given the -65deg rotation puts the largest project upper-right --
# but the legend sits flush in the corner above any label text). Font 8pt.
# =========================================================================
# We draw in *data* coordinates anchored to the upper-RIGHT of the axes,
# so glyph sizes scale with the figure rather than being offset-only.
def data_xy(frac_x: float, frac_y: float):
    """Convert (frac of axes width, frac of axes height) to data coords."""
    return (-LIM + frac_x * (2 * LIM), -LIM + frac_y * (2 * LIM))

# Subtle white bbox behind each row -- no visible frame, just to break
# visual collisions with circles / leader lines drawn underneath.
LEGEND_BBOX = dict(facecolor="white", edgecolor="none",
                   boxstyle="round,pad=0.18", alpha=0.85)

# Right edge of the legend column, left edge of text column.
LEGEND_RIGHT = 0.985   # right edge of all glyphs+text
TEXT_X       = 0.595   # left edge of label text (right-aligned region)
GLYPH_X1     = 0.685   # first glyph center
GLYPH_X2     = 0.730   # second glyph center (where used)
LABEL_X      = 0.775   # left edge of caption text

# Header
hx, hy = data_xy(LABEL_X - 0.085, 0.975)
ax.text(hx, hy, "Encoding", fontsize=9, weight="bold",
        color=PAL["gray_text"], ha="left", va="top", zorder=30,
        bbox=LEGEND_BBOX)

LINE_DY = 0.052   # vertical spacing per row (in axes-fraction)

# Row 1: area = statement count
y_row = 0.975 - LINE_DY - 0.005
# small + larger purple disk
gx1, gy1 = data_xy(GLYPH_X1, y_row)
gx2, gy2 = data_xy(GLYPH_X2, y_row)
glyph_r_small = 0.012 * (2 * LIM)
glyph_r_big   = 0.020 * (2 * LIM)
ax.add_patch(Circle((gx1, gy1), glyph_r_small,
                    facecolor=PAL["accent_purple"], alpha=0.6,
                    edgecolor=PAL["accent_purple"], linewidth=0.8, zorder=30))
ax.add_patch(Circle((gx2, gy2), glyph_r_big,
                    facecolor=PAL["accent_purple"], alpha=0.6,
                    edgecolor=PAL["accent_purple"], linewidth=0.8, zorder=30))
tx, ty = data_xy(LABEL_X, y_row)
ax.text(tx, ty, "area  =  statement count",
        fontsize=8, color=PAL["gray_text"], ha="left", va="center", zorder=30,
        bbox=LEGEND_BBOX)

# Row 2: overlap = frac of edges into Mathlib
y_row -= LINE_DY + 0.008
gx1, gy1 = data_xy(GLYPH_X1 - 0.005, y_row)
gx2, gy2 = data_xy(GLYPH_X2 + 0.005, y_row)
ax.add_patch(Circle((gx1, gy1), 0.028 * (2 * LIM),
                    facecolor=PAL["blue_primary"], alpha=0.18,
                    edgecolor=PAL["blue_primary"], linewidth=0.8, zorder=30))
ax.add_patch(Circle((gx2, gy2), 0.018 * (2 * LIM),
                    facecolor=PAL["accent_purple"], alpha=0.6,
                    edgecolor=PAL["accent_purple"], linewidth=0.8, zorder=30))
tx, ty = data_xy(LABEL_X, y_row)
ax.text(tx, ty, "overlap  =  frac. edges into Mathlib",
        fontsize=8, color=PAL["gray_text"], ha="left", va="center", zorder=30,
        bbox=LEGEND_BBOX)

# Row 3: opacity = NL link strength
y_row -= LINE_DY + 0.005
gx1, gy1 = data_xy(GLYPH_X1, y_row)
gx2, gy2 = data_xy(GLYPH_X2, y_row)
ax.add_patch(Circle((gx1, gy1), glyph_r_small,
                    facecolor=PAL["accent_purple"], alpha=0.25,
                    edgecolor=PAL["accent_purple"], linewidth=0.8, zorder=30))
ax.add_patch(Circle((gx2, gy2), glyph_r_small,
                    facecolor=PAL["accent_purple"], alpha=1.00,
                    edgecolor=PAL["accent_purple"], linewidth=0.8, zorder=30))
tx, ty = data_xy(LABEL_X, y_row)
ax.text(tx, ty, "opacity  =  NL-graph link strength",
        fontsize=8, color=PAL["gray_text"], ha="left", va="center", zorder=30,
        bbox=LEGEND_BBOX)

# Row 4: gold ring = top-5 most NL-linked
y_row -= LINE_DY
gx1, gy1 = data_xy((GLYPH_X1 + GLYPH_X2) / 2, y_row)
# gold-ring + purple disk inline
ring_r  = 0.020 * (2 * LIM)
inner_r = 0.012 * (2 * LIM)
ax.add_patch(Circle((gx1, gy1), ring_r,
                    facecolor="none",
                    edgecolor=PAL["accent_gold"], linewidth=1.5, zorder=30))
ax.add_patch(Circle((gx1, gy1), inner_r,
                    facecolor=PAL["accent_purple"], alpha=0.6,
                    edgecolor=PAL["accent_purple"], linewidth=0.8, zorder=30))
tx, ty = data_xy(LABEL_X, y_row)
ax.text(tx, ty, "gold ring  =  top-5 most NL-linked",
        fontsize=8, color=PAL["gray_text"], ha="left", va="center", zorder=30,
        bbox=LEGEND_BBOX)

# footer
y_row -= LINE_DY - 0.002
fx, fy = data_xy(TEXT_X + 0.02, y_row)
ax.text(fx, fy,
        f"(NL link = mutual rank-1 pair; max = {int(nl_max)})",
        fontsize=7, color=PAL["gray_rule"], ha="left", va="center",
        style="italic", zorder=30, bbox=LEGEND_BBOX)

# =========================================================================
# Save
# =========================================================================
out_dir = Path(__file__).resolve().parents[1] / "out"
out_dir.mkdir(parents=True, exist_ok=True)
pdf_path = out_dir / "ecosystem_overview.pdf"
png_path = out_dir / "ecosystem_overview.png"
fig.savefig(pdf_path, format="pdf")
fig.savefig(png_path, format="png", dpi=300)
print(f"wrote {pdf_path}")
print(f"wrote {png_path}")
