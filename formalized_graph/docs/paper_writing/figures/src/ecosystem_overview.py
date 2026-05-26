"""Ecosystem overview — sorted horizontal bar chart with Mathlib scale
anchor (canonical version).

24 non-Mathlib Lean Repo projects as horizontal bars sorted by NL-link
count (descending). Bar length = statement count (log x-axis, since the
range 24-8205 spans ~2.5 decades and a linear scale collapses the smaller
projects into invisibility next to physlib's 8205). Bar color is
`ACCENT_PURPLE` with opacity linear in NL-link count
(floor 0.30 so zero-NL-link bars remain visible). All 24 project bars
share a thin 0.3pt purple outline. Per-bar NL-link count sits to the
right of each bar in 7pt gray.

Mathlib scale anchor: a single `BLUE_PRIMARY` "ruler" bar at the top
(alpha 0.20) labeled `Mathlib (351,397)`. Drawn on the same log x-axis
so its dominance reads visually (~43x physlib, ~14600x toric). Separated
from the project bars by a thin horizontal rule.

Encoding key (small text block, below x-axis label): two rows — opacity
= NL-link count; bar length = statement count.

Output:
  ../out/ecosystem_overview.pdf
  ../out/ecosystem_overview.png
"""

from __future__ import annotations
import json
from pathlib import Path

import numpy as np
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle
from matplotlib.lines import Line2D

# ---- Palette (figure_style.md s3) ---------------------------------------
PAL = {
    "blue_primary":  "#2E5C8A",
    "gray_text":     "#2A2A2A",
    "gray_rule":     "#999999",
    "gray_bg":       "#F2F2F2",
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
    "axes.spines.top":    False,
    "axes.spines.right":  False,
    "axes.labelcolor":    PAL["gray_text"],
    "xtick.color":        PAL["gray_text"],
    "ytick.color":        PAL["gray_text"],
    "xtick.direction":    "out",
    "ytick.direction":    "out",
    "xtick.major.size":   3,
    "ytick.major.size":   0,    # y-tick marks redundant with bar labels
    "pdf.fonttype":       42,
    "ps.fonttype":        42,
    "savefig.bbox":       "tight",
    "savefig.pad_inches": 0.04,
})

# =========================================================================
# Load data
# =========================================================================
DATA_PATH = Path("/tmp/ecosystem_data.json")
with DATA_PATH.open() as f:
    DATA = json.load(f)

mathlib_total = DATA["mathlib_total"]
projects = DATA["projects"]

# Sort by NL link count descending; ties broken by statement count desc
# so the rank ordering is deterministic.
projects = sorted(projects, key=lambda p: (-p["nl_link_count"], -p["statements"]))

nl_counts = np.array([p["nl_link_count"] for p in projects], dtype=float)
nl_max = nl_counts.max() if nl_counts.max() > 0 else 1.0

ALPHA_FLOOR, ALPHA_TOP = 0.30, 1.00
def alpha_of(n: int) -> float:
    return ALPHA_FLOOR + (ALPHA_TOP - ALPHA_FLOOR) * (n / nl_max)

# =========================================================================
# Figure layout
# =========================================================================
# Single-column EMNLP, taller than wide: 24 bars + Mathlib anchor + key.
FIGSIZE = (3.3, 5.8)

fig, ax = plt.subplots(figsize=FIGSIZE)

N = len(projects)
# y-positions: project bars stack from y=0 (bottom of chart) upward.
# Highest NL-link count goes at the top, so reverse the index order.
y_positions = np.arange(N)[::-1]   # length N, top-most bar = projects[0]

bar_height = 0.78

# Log x-axis. Floor at 10 so the leftmost tick is clean.
X_MIN = 10
X_MAX = 5e5   # leaves room for Mathlib (351k) ruler + value labels

# ---- Project bars -------------------------------------------------------
# (Bars drawn as Rectangles after ax.cla() below; this initial pass is
# discarded but kept to preserve the original two-pass structure.)
for y, p in zip(y_positions, projects):
    n = p["statements"]
    alpha = alpha_of(p["nl_link_count"])
    ax.barh(y, n, height=bar_height,
            left=X_MIN,
            color=PAL["accent_purple"], alpha=alpha,
            edgecolor=PAL["accent_purple"], linewidth=0.3,
            zorder=5)

# Override: matplotlib's barh on a log axis with `left` works in data
# coords. The widths above need to be the absolute right-edge minus left;
# re-emit explicitly with patches for safety.
ax.cla()   # clear and redo properly
ax.set_xscale("log")
ax.set_xlim(X_MIN, X_MAX)

# y axis spans project bars + anchor row above.
ANCHOR_Y = N + 1.4     # mathlib ruler sits above the project bars
ax.set_ylim(-0.7, ANCHOR_Y + 1.0)

# Re-draw project bars as Rectangles so the log-axis left edge is clean.
for y, p in zip(y_positions, projects):
    n = p["statements"]
    alpha = alpha_of(p["nl_link_count"])
    rect = Rectangle((X_MIN, y - bar_height / 2),
                     width=n - X_MIN,
                     height=bar_height,
                     facecolor=PAL["accent_purple"], alpha=alpha,
                     edgecolor=PAL["accent_purple"], linewidth=0.3,
                     zorder=5)
    ax.add_patch(rect)

# ---- Mathlib scale anchor (blue ruler at top) ---------------------------
anchor_h = 0.95
mathlib_rect = Rectangle(
    (X_MIN, ANCHOR_Y - anchor_h / 2),
    width=mathlib_total - X_MIN,
    height=anchor_h,
    facecolor=PAL["blue_primary"],
    alpha=0.20,
    edgecolor=PAL["blue_primary"],
    linewidth=0.3, zorder=5,
)
ax.add_patch(mathlib_rect)
ax.text(mathlib_total * 1.05, ANCHOR_Y,
        f"Mathlib  (351,397)",
        fontsize=8, color=PAL["gray_text"], weight="bold",
        ha="left", va="center", zorder=10)

# Thin horizontal rule separating the anchor row from project bars.
sep_y = ANCHOR_Y - anchor_h / 2 - 0.45
ax.axhline(sep_y, color=PAL["gray_rule"], linewidth=0.5, zorder=3)

# ---- y-tick labels: project names ---------------------------------------
ax.set_yticks(y_positions)
ax.set_yticklabels([p["project"] for p in projects], fontsize=8,
                   color=PAL["gray_text"])

# ---- Per-bar NL-link count (right of bar) -------------------------------
# Place at the bar's right edge in data coords, with a small log-space
# offset for visual gap.
for y, p in zip(y_positions, projects):
    n = p["statements"]
    nl = p["nl_link_count"]
    label = f"NL {nl}" if nl > 0 else "NL 0"
    ax.text(n * 1.15, y, label,
            fontsize=7, color=PAL["gray_rule"], weight="normal",
            ha="left", va="center", zorder=10)

# ---- x-axis: log, "Statements" label ------------------------------------
ax.set_xlabel("Statements (log scale)", fontsize=9, color=PAL["gray_text"])
ax.tick_params(axis="x", which="major", labelsize=8)
ax.tick_params(axis="x", which="minor", length=0)
# Only major ticks at decades: 10, 100, 1k, 10k, 100k.
from matplotlib.ticker import LogLocator, FuncFormatter
ax.xaxis.set_major_locator(LogLocator(base=10, numticks=6))
def _fmt(x, _):
    if x >= 1000:
        return f"{int(x/1000)}k"
    return f"{int(x)}"
ax.xaxis.set_major_formatter(FuncFormatter(_fmt))

# Hide left spine ticks; we already removed marks via rcParams.
ax.spines["left"].set_visible(False)

# =========================================================================
# Encoding key (below x-axis label, in figure coords so it's outside axes)
# =========================================================================
# Use figure coords so the key sits cleanly below the x-axis label
# without colliding with bars or tick labels.
key_text_kw = dict(transform=fig.transFigure, fontsize=7,
                   color=PAL["gray_text"], va="center")

def _key_rect_fig(x_frac, y_frac, w_frac, h_frac, alpha=1.0,
                  edge=None, ew=0.4, fill=PAL["accent_purple"]):
    edge = edge if edge is not None else fill
    fig.patches.append(Rectangle((x_frac, y_frac), w_frac, h_frac,
                                  transform=fig.transFigure,
                                  facecolor=fill, alpha=alpha,
                                  edgecolor=edge, linewidth=ew, zorder=30,
                                  clip_on=False))

KEY_Y_TOP = 0.020
ROW_DY    = 0.018
GLYPH_X   = 0.18
GLYPH_W   = 0.025
GLYPH_H   = 0.013
LABEL_X   = GLYPH_X + 2 * GLYPH_W + 0.018

# Row 1: opacity glyph (low alpha + high alpha) + label
_key_rect_fig(GLYPH_X,             KEY_Y_TOP, GLYPH_W, GLYPH_H, alpha=ALPHA_FLOOR)
_key_rect_fig(GLYPH_X + GLYPH_W,   KEY_Y_TOP, GLYPH_W, GLYPH_H, alpha=ALPHA_TOP)
fig.text(LABEL_X, KEY_Y_TOP + GLYPH_H / 2,
         "opacity = NL-link count",
         fontsize=7, color=PAL["gray_text"], va="center")

# Row 2: bar-length glyph (short + long purple bar) + label
KEY_Y_BOT = KEY_Y_TOP - ROW_DY
_key_rect_fig(GLYPH_X, KEY_Y_BOT, GLYPH_W * 0.6, GLYPH_H, alpha=0.7,
              edge=PAL["accent_purple"], ew=0.3)
_key_rect_fig(GLYPH_X + GLYPH_W, KEY_Y_BOT, GLYPH_W, GLYPH_H, alpha=0.7,
              edge=PAL["accent_purple"], ew=0.3)
fig.text(LABEL_X, KEY_Y_BOT + GLYPH_H / 2,
         "bar length = statement count (log)",
         fontsize=7, color=PAL["gray_text"], va="center")

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
