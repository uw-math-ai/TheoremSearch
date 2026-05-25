"""Ecosystem overview: Mathlib at the center, project repos as a ring of circles.

Three encodings per project circle:
  * circle radius  ~ sqrt(statement count)  (sqrt scaling so Mathlib doesn't eat the figure)
  * overlap with Mathlib blob ~ fraction of decls citing into Mathlib
        d_i = R_mathlib + R_proj_i - (R_mathlib + R_proj_i) * overlap_frac_i
  * fill opacity ~ NL-graph link strength (mutual rank-1 pairs anchored to project)
        linearly normalised across projects to alpha in [0.25, 1.0] so projects
        with 0 NL links still show as visibly faded.

Re-scaling notes (documented per figure_style.md anti-pattern checklist):
  * Citation density in the data is bunched in [0.85, 1.0]; mapping it linearly
    to overlap collapses every project flush onto Mathlib.  We renormalise to a
    visible range:
        overlap_frac = clip(  (cite_pct - 0.80) / 0.20, 0, 1 ) ** 0.85
    Documented inline.
  * Statement counts span 24 -> 351,397 (>14000x).  sqrt scaling on radii keeps
    the smallest project visible while Mathlib still dominates by area.

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
projects = DATA["projects"]   # list of dicts: project, statements, mathlib_cite_pct, nl_link_count

# =========================================================================
# Encodings
# =========================================================================
# Radius scale: r ~ statements ** RADIUS_EXP * k, with RADIUS_EXP=0.42 (between
# log and sqrt). Pure sqrt makes Mathlib 6x larger than the largest project,
# which still eats the figure; 0.42 keeps Mathlib dominant but lets the ring
# of projects be readable.
RADIUS_EXP = 0.42
R_MATHLIB_TARGET = 2.0
k_radius = R_MATHLIB_TARGET / (mathlib_total ** RADIUS_EXP)

def radius_of(n: int) -> float:
    return k_radius * (n ** RADIUS_EXP)

R_mathlib = radius_of(mathlib_total)

# Overlap re-scaling: citation density lives in [~0.85, 1.0] and nearly every
# project sits at 0.99+. Mapping that linearly to fully-nested would collapse
# the figure. We use the alternative mapping documented in the spec:
#     d_i = R_mathlib * (1 - 0.5 * overlap) + R_proj
# which at overlap=1 keeps the project center halfway inside Mathlib (visible
# physical overlap) and at overlap=0 puts it tangent. Then we still need to
# spread projects across the dynamic range, since cite_pct is bunched. We
# re-stretch to use the visible band [0.15, 0.95]:
def overlap_frac(cite_pct: float) -> float:
    raw = (cite_pct - 0.80) / 0.20
    raw = max(0.0, min(1.0, raw))
    # Stretch so even modest differences in cite_pct read visually.
    return 0.15 + 0.80 * (raw ** 0.6)

# Opacity from NL link count, normalised to [0.25, 1.0]
nl_counts = np.array([p["nl_link_count"] for p in projects], dtype=float)
nl_max = nl_counts.max() if nl_counts.max() > 0 else 1.0
def alpha_of(n_links: int) -> float:
    return 0.25 + 0.75 * (n_links / nl_max)

# =========================================================================
# Layout: arrange project circles around Mathlib center
# =========================================================================
# Pick a ring radius such that the largest project (physlib) doesn't collide
# with its angular neighbours and even minimum-overlap projects fit in frame.
# Center distance per project: d_i = R_M + R_p - (R_M + R_p) * overlap
N = len(projects)
angles = np.linspace(0, 2 * np.pi, N, endpoint=False)
# Rotate so largest project (index 0 -> physlib) sits up-right for label space.
angles = angles + np.radians(-65)

centers = []
for p, theta in zip(projects, angles):
    R_p = radius_of(p["statements"])
    of = overlap_frac(p["mathlib_cite_pct"])
    # Center distance: project sits with its center at (R_mathlib*(1 - 0.5*overlap) + R_proj)
    # so overlap=0 -> tangent (no overlap); overlap=1 -> center is halfway inside
    # Mathlib (substantial visible overlap).
    # Max nesting: project center sits at 0.75*R_mathlib (so ~25% of Mathlib's
    # radius peeks past the project) rather than halfway inside. This keeps
    # Mathlib's rim visible everywhere and reads more like "ring overlapping
    # Mathlib" than "ring of holes inside Mathlib".
    d = R_mathlib * (1 - 0.25 * of) + R_p * 0.6
    cx = d * math.cos(theta)
    cy = d * math.sin(theta)
    centers.append((cx, cy, R_p, of))

# Scene extent
max_extent = max(max(abs(c[0]) + c[2], abs(c[1]) + c[2]) for c in centers)
PAD = 1.6
LIM = max(max_extent + PAD, R_mathlib + PAD)

# =========================================================================
# Choose labels: top 8 by NL-link count, then fill with top by size
# =========================================================================
labelled_set: set[str] = set()
by_nl = sorted(projects, key=lambda p: -p["nl_link_count"])
for p in by_nl:
    if p["nl_link_count"] == 0:
        break
    labelled_set.add(p["project"])
    if len(labelled_set) >= 8:
        break
by_size = sorted(projects, key=lambda p: -p["statements"])
for p in by_size:
    if len(labelled_set) >= 8:
        break
    labelled_set.add(p["project"])

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
for (cx, cy, R_p, of), p in zip(centers, projects):
    a = alpha_of(p["nl_link_count"])
    ax.add_patch(Circle((cx, cy), R_p,
                        facecolor=PAL["accent_purple"], alpha=a,
                        edgecolor=PAL["accent_purple"], linewidth=1.0,
                        zorder=3))

# Labels (only for the chosen top-8). Push labels well outside their circles
# and connect with a thin leader line so they don't collide on the right side.
for (cx, cy, R_p, of), p in zip(centers, projects):
    if p["project"] not in labelled_set:
        continue
    theta = math.atan2(cy, cx)
    # Anchor point on the circle edge facing outward
    ax_pt = (cx + R_p * math.cos(theta), cy + R_p * math.sin(theta))
    # Label sits further out
    label_radius_extra = 0.65
    lx = cx + (R_p + label_radius_extra) * math.cos(theta)
    ly = cy + (R_p + label_radius_extra) * math.sin(theta)
    ha = "left"   if math.cos(theta) > 0.10 else ("right" if math.cos(theta) < -0.10 else "center")
    va = "bottom" if math.sin(theta) > 0.10 else ("top"   if math.sin(theta) < -0.10 else "center")
    # leader
    ax.plot([ax_pt[0], lx], [ax_pt[1], ly],
            color=PAL["gray_rule"], lw=0.5, alpha=0.6, zorder=19)
    is_top_nl = p["nl_link_count"] >= 20
    ax.text(lx, ly, p["project"],
            fontsize=8,
            color=PAL["gold_dark"] if is_top_nl else PAL["gray_text"],
            weight="bold" if is_top_nl else "normal",
            ha=ha, va=va, zorder=21, bbox=LABEL_BBOX)

# =========================================================================
# Legend (manual, three encodings)
# =========================================================================
lx0 = -LIM + 0.05 * (2 * LIM)
ly0 =  LIM - 0.05 * (2 * LIM)
lw  = 0.34 * (2 * LIM)
lh  = 0.22 * (2 * LIM)
legend_ax_rect = [0.015, 0.74, 0.31, 0.245]  # figure-coord inset
lax = fig.add_axes(legend_ax_rect)
lax.set_xlim(0, 1); lax.set_ylim(0, 1)
lax.set_xticks([]); lax.set_yticks([])
for spine in lax.spines.values():
    spine.set_edgecolor(PAL["gray_rule"])
    spine.set_linewidth(0.5)
lax.set_facecolor("white")

# row 1: size = statement count (sqrt scale)
lax.text(0.04, 0.86, "Encoding", fontsize=8.5, weight="bold",
         color=PAL["gray_text"], ha="left", va="center")

lax.add_patch(Circle((0.10, 0.66), 0.035, facecolor=PAL["accent_purple"],
                     alpha=0.6, edgecolor=PAL["accent_purple"], linewidth=0.8,
                     transform=lax.transAxes))
lax.add_patch(Circle((0.18, 0.66), 0.060, facecolor=PAL["accent_purple"],
                     alpha=0.6, edgecolor=PAL["accent_purple"], linewidth=0.8,
                     transform=lax.transAxes))
lax.text(0.30, 0.66, "area  =  statement count",
         fontsize=8, color=PAL["gray_text"], ha="left", va="center")

# row 2: overlap = citation density into Mathlib
lax.add_patch(Circle((0.13, 0.44), 0.07, facecolor=PAL["blue_primary"],
                     alpha=0.18, edgecolor=PAL["blue_primary"], linewidth=0.8,
                     transform=lax.transAxes))
lax.add_patch(Circle((0.20, 0.44), 0.045, facecolor=PAL["accent_purple"],
                     alpha=0.6, edgecolor=PAL["accent_purple"], linewidth=0.8,
                     transform=lax.transAxes))
lax.text(0.30, 0.44, "overlap  =  fraction citing Mathlib",
         fontsize=8, color=PAL["gray_text"], ha="left", va="center")

# row 3: opacity = NL link strength
lax.add_patch(Circle((0.10, 0.22), 0.038, facecolor=PAL["accent_purple"],
                     alpha=0.25, edgecolor=PAL["accent_purple"], linewidth=0.8,
                     transform=lax.transAxes))
lax.add_patch(Circle((0.19, 0.22), 0.038, facecolor=PAL["accent_purple"],
                     alpha=1.00, edgecolor=PAL["accent_purple"], linewidth=0.8,
                     transform=lax.transAxes))
lax.text(0.30, 0.22, "opacity  =  NL-graph link strength",
         fontsize=8, color=PAL["gray_text"], ha="left", va="center")

# small footer with NL-link max for context
lax.text(0.04, 0.05,
         f"(NL link = mutual rank-1 pair; max = {int(nl_max)} pairs)",
         fontsize=6.8, color=PAL["gray_rule"], ha="left", va="center",
         style="italic")

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
