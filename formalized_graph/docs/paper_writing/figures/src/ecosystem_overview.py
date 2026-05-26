"""Ecosystem overview: Mathlib at the center, project repos as a ring of
*separate* circles linked back to Mathlib by per-project connector lines.

Encodings:
  * Mathlib disk: area ~ statement count (~351k), `BLUE_PRIMARY` low-alpha
    fill, solid 1pt edge, centered.
  * 24 project circles in a ring around Mathlib at radius `R_RING`, sized
    by statement count using the same sqrt-like exponent (0.42) as Mathlib.
    Color: `ACCENT_PURPLE`; opacity carries NL-graph mutual-rank-1 link
    strength (alpha in [0.25, 1.0]).
  * Per-project connector line from the project's inner edge to Mathlib's
    outer edge along the radial direction. Line width is linear in
    `frac_mathlib_edges` (observed [0.68, 0.96]) mapped to [0.4pt, 3.0pt].
    Color: `BLUE_PRIMARY`, alpha 0.55. No arrowhead -- it's a relation,
    not a direction.
  * Top-5 NL-linked projects get a gold ring (`ACCENT_GOLD`, 1.5pt) just
    outside their circle and a leader-line label outside the ring.

Why this design (vs. the previous overlap encoding):
    The overlap encoding (project circles biting into Mathlib's disk by a
    fraction proportional to citation density) read visually as "this
    project is a subset of Mathlib." Replaced with a connector encoding
    so projects are clearly OUTSIDE Mathlib but linked to it
    (figure_style.md s8.2).

Paper integration (LaTeX-first; no paper prose lives in the figure):

\\begin{figure}[t]
  \\centering
  \\includegraphics[width=\\linewidth]{figures/out/ecosystem_overview.pdf}
  \\caption{Mathlib (centre) and the 24 non-Mathlib Lean Repo projects (ring).
           Circle area is proportional to statement count; connector width
           is proportional to the fraction of each project's outgoing
           formal_dependency edges that target Mathlib (range
           [0.68, 0.96]); opacity is proportional to the project's count of
           mutual rank-1 pairs against the informal NL corpus (max 112 for
           brownian-motion). Gold rings mark the top-5 most NL-linked
           projects: brownian-motion, pfr, carleson, FLT, toric. Per-project
           numbers are in Table~\\ref{tab:ecosystem-overview}.}
  \\label{fig:ecosystem-overview}
\\end{figure}

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
from matplotlib.lines import Line2D

# ---- Palette (figure_style.md s3) ---------------------------------------
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
                  linewidth=0.4, boxstyle="round,pad=0.22", alpha=0.85)

# =========================================================================
# Load data (reuse the existing RDS-built fixture)
# =========================================================================
DATA_PATH = Path("/tmp/ecosystem_data.json")
with DATA_PATH.open() as f:
    DATA = json.load(f)

mathlib_total = DATA["mathlib_total"]
projects = DATA["projects"]   # list of dicts incl. frac_mathlib_edges, nl_link_count

# =========================================================================
# Encodings
# =========================================================================
# Radius: between sqrt and log (exp=0.42), same as prior rev.
RADIUS_EXP = 0.42
R_MATHLIB_TARGET = 2.0
k_radius = R_MATHLIB_TARGET / (mathlib_total ** RADIUS_EXP)

def radius_of(n: int) -> float:
    return k_radius * (n ** RADIUS_EXP)

R_mathlib = radius_of(mathlib_total)

# ---- Connector width: linear in frac_mathlib_edges ----------------------
edge_fracs = sorted(p["frac_mathlib_edges"] for p in projects)
f_lo = min(edge_fracs)
f_hi = max(edge_fracs)
LW_MIN, LW_MAX = 0.4, 3.0   # points
def connector_lw(frac: float) -> float:
    if f_hi <= f_lo:
        return 0.5 * (LW_MIN + LW_MAX)
    t = (frac - f_lo) / (f_hi - f_lo)
    return LW_MIN + t * (LW_MAX - LW_MIN)

print(f"connector width: linear, raw [{f_lo:.3f}, {f_hi:.3f}] -> "
      f"lw [{LW_MIN}pt, {LW_MAX}pt]")
for p in sorted(projects, key=lambda d: d["frac_mathlib_edges"]):
    print(f"    {p['project']:40s} frac={p['frac_mathlib_edges']:.3f}"
          f"  -> lw={connector_lw(p['frac_mathlib_edges']):.2f}pt")

# ---- Opacity from NL link count -----------------------------------------
nl_counts = np.array([p["nl_link_count"] for p in projects], dtype=float)
nl_max = nl_counts.max() if nl_counts.max() > 0 else 1.0
def alpha_of(n_links: int) -> float:
    return 0.25 + 0.75 * (n_links / nl_max)

# ---- Top 5 NL-linked (gold-ring set) ------------------------------------
top5_nl = sorted(projects, key=lambda p: -p["nl_link_count"])[:5]
top5_set = {p["project"] for p in top5_nl}
print("top 5 NL-linked projects (gold ring + label):")
for p in top5_nl:
    print(f"    {p['project']:40s} nl_links={p['nl_link_count']}")

# =========================================================================
# Layout: project circles in a ring around Mathlib
# =========================================================================
# Ring radius chosen so the gap between Mathlib's edge and the NEAREST
# project's edge is >= 20% of R_mathlib. Largest project radius dominates
# the gap requirement, so use it to set R_RING.
project_radii = [radius_of(p["statements"]) for p in projects]
R_proj_max = max(project_radii)
GAP_FRAC = 0.30   # >= 0.20 required; 0.30 gives clear breathing room
R_RING = R_mathlib + R_proj_max + GAP_FRAC * R_mathlib

# Nearest project edge to Mathlib edge:
nearest_gap = R_RING - R_proj_max - R_mathlib
print(f"ring radius R_RING = {R_RING:.3f} "
      f"(R_mathlib={R_mathlib:.3f}, R_proj_max={R_proj_max:.3f})")
print(f"min edge-to-edge gap from Mathlib = {nearest_gap:.3f} "
      f"({100*nearest_gap/R_mathlib:.0f}% of R_mathlib)")

N = len(projects)
angles = np.linspace(0, 2 * np.pi, N, endpoint=False)
# Rotate so the upper-left quadrant has a project but leaves room for
# the legend in the lower-left corner.
angles = angles + np.radians(-65)

centers = []
for p, theta in zip(projects, angles):
    R_p = radius_of(p["statements"])
    cx = R_RING * math.cos(theta)
    cy = R_RING * math.sin(theta)
    centers.append((cx, cy, R_p, theta))

# =========================================================================
# Figure bounds
# =========================================================================
# Extra padding for top-5 leader labels which extend beyond the ring.
LABEL_PAD = 1.5
max_extent = max(max(abs(cx) + R_p, abs(cy) + R_p)
                 for (cx, cy, R_p, _) in centers)
LIM = max_extent + LABEL_PAD

# =========================================================================
# Draw
# =========================================================================
fig, ax = plt.subplots(figsize=(7.0, 7.0))
ax.set_aspect("equal")
ax.set_xlim(-LIM, LIM)
ax.set_ylim(-LIM, LIM)
ax.set_axis_off()

# ---- Connectors (drawn first, behind everything) ------------------------
for (cx, cy, R_p, theta), p in zip(centers, projects):
    # From Mathlib's outer edge to the project's inner edge, along radial.
    x0 = R_mathlib * math.cos(theta)
    y0 = R_mathlib * math.sin(theta)
    x1 = (R_RING - R_p) * math.cos(theta)
    y1 = (R_RING - R_p) * math.sin(theta)
    lw = connector_lw(p["frac_mathlib_edges"])
    ax.plot([x0, x1], [y0, y1],
            color=PAL["blue_primary"], alpha=0.55, linewidth=lw,
            solid_capstyle="round", zorder=2)

# ---- Mathlib (centered, dominant) ---------------------------------------
ax.add_patch(Circle((0, 0), R_mathlib,
                    facecolor=PAL["blue_primary"], alpha=0.18,
                    edgecolor=PAL["blue_primary"], linewidth=1.0, zorder=3))
ax.text(0, 0, "Mathlib",
        fontsize=14, weight="bold", color=PAL["blue_primary"],
        ha="center", va="center", zorder=20,
        bbox=dict(facecolor="white", edgecolor="none",
                  boxstyle="round,pad=0.20", alpha=0.85))

# ---- Project circles ----------------------------------------------------
for (cx, cy, R_p, theta), p in zip(centers, projects):
    a = alpha_of(p["nl_link_count"])
    ax.add_patch(Circle((cx, cy), R_p,
                        facecolor=PAL["accent_purple"], alpha=a,
                        edgecolor=PAL["accent_purple"], linewidth=1.0,
                        zorder=5))
    if p["project"] in top5_set:
        # Stroke just outside the purple circle.
        ring_extra = 0.012 * LIM
        ax.add_patch(Circle((cx, cy), R_p + ring_extra,
                            facecolor="none",
                            edgecolor=PAL["accent_gold"],
                            linewidth=1.5,
                            zorder=6))

# =========================================================================
# Labels: top-5 NL projects only, with leader lines outside the ring
# =========================================================================
labelled_set = set(top5_set)
to_label = []
for (cx, cy, R_p, theta), p in zip(centers, projects):
    if p["project"] in labelled_set:
        to_label.append((theta, cx, cy, R_p, p))
to_label.sort(key=lambda x: x[0])

# Default radial extra distance from circle edge to label anchor.
DEFAULT_EXTRA = 0.85
EXTRA_BUMP    = 1.55
MIN_SEP = math.radians(360 / len(projects) * 1.3)
extras = [DEFAULT_EXTRA] * len(to_label)
for i in range(len(to_label)):
    j = (i + 1) % len(to_label)
    a_i, a_j = to_label[i][0], to_label[j][0]
    sep = (a_j - a_i) % (2 * math.pi)
    if sep < MIN_SEP:
        ni = to_label[i][4]["nl_link_count"]
        nj = to_label[j][4]["nl_link_count"]
        push = i if ni <= nj else j
        extras[push] = EXTRA_BUMP

for (theta, cx, cy, R_p, p), extra in zip(to_label, extras):
    anchor_x = cx + R_p * math.cos(theta)
    anchor_y = cy + R_p * math.sin(theta)
    lx = cx + (R_p + extra) * math.cos(theta)
    ly = cy + (R_p + extra) * math.sin(theta)
    ha = "left"   if math.cos(theta) > 0.10 else ("right" if math.cos(theta) < -0.10 else "center")
    va = "bottom" if math.sin(theta) > 0.10 else ("top"   if math.sin(theta) < -0.10 else "center")
    ax.plot([anchor_x, lx], [anchor_y, ly],
            color=PAL["gray_rule"], lw=0.5, alpha=0.6, zorder=19)
    ax.text(lx, ly, p["project"],
            fontsize=9,
            color=PAL["gold_dark"], weight="bold",
            ha=ha, va=va, zorder=21, bbox=LABEL_BBOX)

# =========================================================================
# Encoding legend -- lower-left corner (rotation puts no project there)
# =========================================================================
def data_xy(frac_x: float, frac_y: float):
    """Convert (frac of axes width, frac of axes height) to data coords."""
    return (-LIM + frac_x * (2 * LIM), -LIM + frac_y * (2 * LIM))

LEGEND_BBOX = dict(facecolor="white", edgecolor="none",
                   boxstyle="round,pad=0.18", alpha=0.90)

# Glyph + label column layout (axes-fraction).
GLYPH_X1 = 0.030
GLYPH_X2 = 0.085
LABEL_X  = 0.115

# Header
hx, hy = data_xy(GLYPH_X1, 0.205)
ax.text(hx, hy, "Encoding", fontsize=9, weight="bold",
        color=PAL["gray_text"], ha="left", va="center", zorder=30,
        bbox=LEGEND_BBOX)

LINE_DY = 0.048

# Row 1: area = statement count  (two purple disks, small + large)
y_row = 0.205 - LINE_DY
gx1, gy1 = data_xy(GLYPH_X1, y_row)
gx2, gy2 = data_xy(GLYPH_X2, y_row)
glyph_r_small = 0.011 * (2 * LIM)
glyph_r_big   = 0.019 * (2 * LIM)
ax.add_patch(Circle((gx1, gy1), glyph_r_small,
                    facecolor=PAL["accent_purple"], alpha=0.6,
                    edgecolor=PAL["accent_purple"], linewidth=0.8, zorder=30))
ax.add_patch(Circle((gx2, gy2), glyph_r_big,
                    facecolor=PAL["accent_purple"], alpha=0.6,
                    edgecolor=PAL["accent_purple"], linewidth=0.8, zorder=30))
tx, ty = data_xy(LABEL_X + 0.025, y_row)
ax.text(tx, ty, "area  =  statement count",
        fontsize=8, color=PAL["gray_text"], ha="left", va="center", zorder=30,
        bbox=LEGEND_BBOX)

# Row 2: connector = frac. edges into Mathlib  (two line segments, thin + thick)
y_row -= LINE_DY
gy = data_xy(0, y_row)[1]
gxL1 = data_xy(GLYPH_X1 - 0.005, 0)[0]
gxL2 = data_xy(GLYPH_X2 + 0.010, 0)[0]
# split the glyph cell into a top (thin) and bottom (thick) row visually
dy_pair = 0.010 * (2 * LIM)
ax.plot([gxL1, gxL2], [gy + dy_pair * 0.5, gy + dy_pair * 0.5],
        color=PAL["blue_primary"], alpha=0.55, linewidth=LW_MIN,
        solid_capstyle="round", zorder=30)
ax.plot([gxL1, gxL2], [gy - dy_pair * 0.5, gy - dy_pair * 0.5],
        color=PAL["blue_primary"], alpha=0.55, linewidth=LW_MAX,
        solid_capstyle="round", zorder=30)
tx, ty = data_xy(LABEL_X + 0.025, y_row)
ax.text(tx, ty, "connector  =  frac. edges into Mathlib",
        fontsize=8, color=PAL["gray_text"], ha="left", va="center", zorder=30,
        bbox=LEGEND_BBOX)

# Row 3: opacity = NL-graph link strength
y_row -= LINE_DY
gx1, gy1 = data_xy(GLYPH_X1, y_row)
gx2, gy2 = data_xy(GLYPH_X2, y_row)
ax.add_patch(Circle((gx1, gy1), glyph_r_small,
                    facecolor=PAL["accent_purple"], alpha=0.25,
                    edgecolor=PAL["accent_purple"], linewidth=0.8, zorder=30))
ax.add_patch(Circle((gx2, gy2), glyph_r_small,
                    facecolor=PAL["accent_purple"], alpha=1.00,
                    edgecolor=PAL["accent_purple"], linewidth=0.8, zorder=30))
tx, ty = data_xy(LABEL_X + 0.025, y_row)
ax.text(tx, ty, "opacity  =  NL-graph link strength",
        fontsize=8, color=PAL["gray_text"], ha="left", va="center", zorder=30,
        bbox=LEGEND_BBOX)

# Row 4: gold ring = top-5 most NL-linked
y_row -= LINE_DY
gx_mid = data_xy((GLYPH_X1 + GLYPH_X2) / 2, y_row)
ring_r  = 0.018 * (2 * LIM)
inner_r = 0.011 * (2 * LIM)
ax.add_patch(Circle((gx_mid[0], gx_mid[1]), ring_r,
                    facecolor="none",
                    edgecolor=PAL["accent_gold"], linewidth=1.5, zorder=30))
ax.add_patch(Circle((gx_mid[0], gx_mid[1]), inner_r,
                    facecolor=PAL["accent_purple"], alpha=0.6,
                    edgecolor=PAL["accent_purple"], linewidth=0.8, zorder=30))
tx, ty = data_xy(LABEL_X + 0.025, y_row)
ax.text(tx, ty, "gold ring  =  top-5 most NL-linked",
        fontsize=8, color=PAL["gray_text"], ha="left", va="center", zorder=30,
        bbox=LEGEND_BBOX)

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
