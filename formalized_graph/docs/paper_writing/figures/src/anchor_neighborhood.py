"""Anchor blueprint-pair diagram — matplotlib version of the §11 dual-plane
theme. Mirrors anchor_neighborhood.tex exactly: informal red plane on top,
formal blue plane on bottom, vertical green \\lean{} links, with two
unformalized informal neighbors, one formalized k=1 neighbor (with formal
partner), and one formalized k=2 neighbor (further from anchor).

Build: python anchor_neighborhood.py
Output: ../out/anchor_neighborhood_mpl.pdf
"""

from __future__ import annotations
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon, Circle

# ---- Palette (figure_style.md §2) ---------------------------------------
PAL = {
    "blue_primary":  "#2E5C8A",
    "accent_red":    "#C8553D",
    "accent_green":  "#5B8C5A",
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

# ---- Plane geometry (figure_style.md §11) -------------------------------
PLANE_W, DX, DY = 7.4, 1.5, 0.95
TOP_Y, BOT_Y    = 5.2, 0.0


def world(u: float, v: float, plane_y: float) -> tuple[float, float]:
    """Plane-local (u, v) -> world (x, y). v=0 front, v=1 back."""
    return (u + v * DX, plane_y + v * DY)


def plane_poly(plane_y: float) -> list[tuple[float, float]]:
    return [
        (0.0,       plane_y),
        (PLANE_W,   plane_y),
        (PLANE_W + DX, plane_y + DY),
        (DX,        plane_y + DY),
    ]


# ---- Node positions (plane-local) ---------------------------------------
NODES = {
    # informal
    "Ai": (3.6, 0.50, "anchor_i"),
    "N1": (1.1, 0.78, "unform"),    # unformalized, back-left
    "N2": (1.8, 0.05, "unform"),    # unformalized, front-left
    "N3": (5.2, 0.65, "informal"),  # formalized k=1
    "N4": (6.5, 0.95, "informal"),  # formalized k=2 (via N3)
    # formal
    "Af":  (3.6, 0.50, "anchor_f"),
    "N3f": (5.2, 0.65, "formal"),
    "N4f": (6.5, 0.95, "formal"),
}
IS_FORMAL = {"Af", "N3f", "N4f"}


def xy(name: str) -> tuple[float, float]:
    u, v, _ = NODES[name]
    return world(u, v, BOT_Y if name in IS_FORMAL else TOP_Y)


# ---- Figure --------------------------------------------------------------
fig, ax = plt.subplots(figsize=(7.0, 5.2))
ax.set_aspect("equal")
ax.set_xlim(-0.4, PLANE_W + DX + 0.4)
ax.set_ylim(BOT_Y - 1.9, TOP_Y + DY + 0.95)
ax.axis("off")

# Plane parallelograms
ax.add_patch(Polygon(plane_poly(TOP_Y), closed=True,
                     facecolor=PAL["accent_red"], alpha=0.05,
                     edgecolor=PAL["accent_red"], linewidth=0.5,
                     joinstyle="miter", zorder=1))
ax.add_patch(Polygon(plane_poly(BOT_Y), closed=True,
                     facecolor=PAL["blue_primary"], alpha=0.05,
                     edgecolor=PAL["blue_primary"], linewidth=0.5,
                     joinstyle="miter", zorder=1))

# Plane labels (OUTSIDE the parallelograms)
ax.text(0, TOP_Y + DY + 0.45, "informal dependency graph",
        color=PAL["accent_red"], fontsize=10,
        style="italic", weight="bold", ha="left", va="bottom")
ax.text(0, BOT_Y - 0.50, "formal dependency graph (Lean)",
        color=PAL["blue_primary"], fontsize=10,
        style="italic", weight="bold", ha="left", va="top")

# ---- In-plane edges (drawn first; nodes overlap them) -------------------
i_edges = [("Ai", "N1"), ("Ai", "N2"), ("Ai", "N3"), ("N3", "N4")]
f_edges = [("Af", "N3f"), ("N3f", "N4f")]

for a, b in i_edges:
    (ax0, ay0), (ax1, ay1) = xy(a), xy(b)
    ax.plot([ax0, ax1], [ay0, ay1], color=PAL["accent_red"],
            alpha=0.6, lw=0.7, zorder=2)
for a, b in f_edges:
    (ax0, ay0), (ax1, ay1) = xy(a), xy(b)
    ax.plot([ax0, ax1], [ay0, ay1], color=PAL["blue_primary"],
            alpha=0.7, lw=0.7, zorder=2)

# ---- Vertical \lean{} links --------------------------------------------
# Anchor pair: thicker, saturated green
(ax0, ay0), (ax1, ay1) = xy("Ai"), xy("Af")
ax.plot([ax0, ax1], [ay0, ay1], color=PAL["accent_green"],
        lw=1.4, ls=(0, (3, 1.5)), zorder=2)
# Other formalized pairs: thinner dashed
for a, b in [("N3", "N3f"), ("N4", "N4f")]:
    (ax0, ay0), (ax1, ay1) = xy(a), xy(b)
    ax.plot([ax0, ax1], [ay0, ay1], color=PAL["accent_green"],
            alpha=0.85, lw=0.7, ls=(0, (3, 1.5)), zorder=2)

# ---- Nodes --------------------------------------------------------------
def draw_node(name: str):
    x, y = xy(name)
    _, _, kind = NODES[name]
    if kind == "anchor_i":
        ax.add_patch(Circle((x, y), 0.36,
                            facecolor=PAL["accent_red"],
                            edgecolor=PAL["accent_red"], linewidth=1.0,
                            zorder=4))
        ax.text(x, y, "A", color="white",
                fontsize=10, weight="bold", ha="center", va="center", zorder=5)
    elif kind == "anchor_f":
        ax.add_patch(Circle((x, y), 0.36,
                            facecolor=PAL["blue_primary"],
                            edgecolor=PAL["blue_primary"], linewidth=1.0,
                            zorder=4))
        ax.text(x, y, "A", color="white",
                fontsize=10, weight="bold", ha="center", va="center", zorder=5)
    elif kind == "informal":
        ax.add_patch(Circle((x, y), 0.26,
                            facecolor=PAL["accent_red"], alpha=0.85,
                            edgecolor=PAL["accent_red"], linewidth=0.6,
                            zorder=4))
    elif kind == "unform":
        ax.add_patch(Circle((x, y), 0.26,
                            facecolor=(0.78, 0.33, 0.24, 0.10),  # red @ 8%
                            edgecolor=PAL["accent_red"], linewidth=1.4,
                            zorder=4))
    elif kind == "formal":
        ax.add_patch(Circle((x, y), 0.26,
                            facecolor=PAL["blue_primary"], alpha=0.90,
                            edgecolor=PAL["blue_primary"], linewidth=0.6,
                            zorder=4))


for name in NODES:
    draw_node(name)

# ---- Annotations --------------------------------------------------------
# Anchor pair label
ax_x, ay = xy("Ai")
af_x, ay2 = xy("Af")
mid = ((ax_x + af_x) / 2, (ay + ay2) / 2)
ax.text(mid[0] - 0.25, mid[1] + 0.10, "anchor: blueprint pair",
        color=PAL["accent_green"], fontsize=8, style="italic",
        ha="right", va="center")
ax.text(mid[0] - 0.25, mid[1] - 0.20, r"(\lean{})",
        color=PAL["accent_green"], fontsize=7.5, style="italic",
        family="monospace", ha="right", va="center")

# Unformalized labels
for name in ("N1", "N2"):
    nx, ny = xy(name)
    ax.text(nx - 0.34, ny, "unformalized",
            color=PAL["accent_red"], fontsize=8, weight="bold",
            ha="right", va="center")

# Formalized k=1
n3x, n3y = xy("N3")
ax.text(n3x + 0.34, n3y, r"formalized $k{=}1$",
        color=PAL["gray_text"], fontsize=8, ha="left", va="center")

# Formalized k=2 (further)
n4x, n4y = xy("N4")
ax.text(n4x + 0.34, n4y + 0.10, r"formalized $k{=}2$",
        color=PAL["gray_text"], fontsize=8, ha="left", va="center")
ax.text(n4x + 0.34, n4y - 0.18, "(further)",
        color=PAL["gray_text"], fontsize=7.5, style="italic",
        ha="left", va="center")

# ---- Legend (single row below the bottom plane label) ------------------
legend_y = BOT_Y - 1.45
items = [
    (PAL["accent_red"], None, 0.6, "formalized informal"),
    ((0.78, 0.33, 0.24, 0.10), PAL["accent_red"], 1.4, "unformalized informal"),
    (PAL["blue_primary"], None, 0.6, "formal Lean decl"),
]
x_cursor = 0.0
for face, edge, lw, label in items:
    ax.add_patch(Circle((x_cursor + 0.15, legend_y), 0.13,
                        facecolor=face,
                        edgecolor=edge or face, linewidth=lw, zorder=4))
    ax.text(x_cursor + 0.35, legend_y, "  " + label,
            color=PAL["gray_text"], fontsize=8, ha="left", va="center")
    x_cursor += 2.95
# dashed line for the \lean{} legend entry
ax.plot([x_cursor + 0.02, x_cursor + 0.52], [legend_y, legend_y],
        color=PAL["accent_green"], lw=0.9, ls=(0, (3, 1.5)))
ax.text(x_cursor + 0.62, legend_y, r"  \lean{}",
        color=PAL["gray_text"], fontsize=8, family="monospace",
        ha="left", va="center")

out = Path(__file__).resolve().parents[1] / "out" / "anchor_neighborhood_mpl.pdf"
out.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(out, format="pdf")
print(f"wrote {out}")
