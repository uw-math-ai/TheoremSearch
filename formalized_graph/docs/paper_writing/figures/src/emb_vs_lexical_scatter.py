"""Scatter: embedding cosine vs char-4gram Jaccard for f->i rank-1 gold pairs,
emitted as FOUR independent single-column figures (one per bidirectional
agreement bucket) so each can be inserted standalone in the paper.

Shared 0-1 axes across all four PDFs make them mentally overlay-able. Each
panel carries its own headline (bucket + n) in the bucket color, its own
Spearman rho, and full axis labels because each PDF stands alone in print.

Data prep: /tmp/build_emb_vs_lexical.py (reproduces nl_corr's f2i seed=0
sample, attaches IDs and agreement bucket per pair). Cached snapshot at
`emb_vs_lexical_scatter_data.csv` next to this script.

Build:  python emb_vs_lexical_scatter.py
Outputs:
  ../out/emb_vs_lexical_both_correct.pdf  (+ .png)
  ../out/emb_vs_lexical_f2i_only.pdf      (+ .png)
  ../out/emb_vs_lexical_i2f_only.pdf      (+ .png)
  ../out/emb_vs_lexical_neither.pdf       (+ .png)
"""
from __future__ import annotations
import csv
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt

# ---- Palette (figure_style.md §2) ---------------------------------------
PAL = {
    "blue_primary":  "#2E5C8A",
    "gray_text":     "#2A2A2A",
    "gray_rule":     "#999999",
    "accent_red":    "#C8553D",
    "accent_green":  "#5B8C5A",
    "accent_purple": "#7E5B9E",
}

BUCKET_COLOR = {
    "both_correct": PAL["accent_green"],    # #5B8C5A
    "f2i_only":     PAL["blue_primary"],    # #2E5C8A
    "i2f_only":     PAL["accent_purple"],   # #7E5B9E
    "neither":      PAL["accent_red"],      # #C8553D
}
BUCKET_LABEL = {
    "both_correct": "Both directions rank-1 correct",
    "f2i_only":     "Only formal$\\to$informal correct",
    "i2f_only":     "Only informal$\\to$formal correct",
    "neither":      "Neither direction rank-1 correct",
}
BUCKET_ORDER = ["both_correct", "f2i_only", "i2f_only", "neither"]

# ---- rcParams (figure_style.md §5) --------------------------------------
mpl.rcParams.update({
    "font.family":        "sans-serif",
    "font.sans-serif":    ["Helvetica", "Arial", "DejaVu Sans"],
    "font.size":          9,
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
    "ytick.major.size":   3,
    "savefig.bbox":       "tight",
    "savefig.pad_inches": 0.02,
    "pdf.fonttype":       42,
    "ps.fonttype":        42,
})

# Single-column width 3.3in. Height bumped by 0.3in over the 4:3 base
# (2.475 -> 2.775) to make room for a left-aligned title above the panel.
FIGSIZE_1COL = (3.3, 2.775)
SHARED_XLIM = (0.0, 1.0)
SHARED_YLIM = (0.0, 1.0)


def _spearman(xs, ys):
    n = len(xs)
    def rank(a):
        o = sorted(range(n), key=lambda i: a[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and a[o[j + 1]] == a[o[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[o[k]] = avg
            i = j + 1
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = sum((rx[i] - mx) ** 2 for i in range(n)) ** 0.5
    dy = sum((ry[i] - my) ** 2 for i in range(n)) ** 0.5
    return num / (dx * dy)


def plot_bucket(name: str, color: str, pts: list[tuple[float, float]],
                out_pdf: Path, out_png: Path) -> float:
    """Render one single-column scatter figure for `name`. Returns Spearman rho."""
    xs, ys = zip(*pts)
    rho = _spearman(list(xs), list(ys))
    n = len(pts)

    fig, ax = plt.subplots(figsize=FIGSIZE_1COL)

    ax.scatter(xs, ys,
               s=17, alpha=0.55,
               c=color, edgecolor="none")

    ax.set_xlim(*SHARED_XLIM)
    ax.set_ylim(*SHARED_YLIM)
    ax.set_xticks([0.0, 0.25, 0.5, 0.75, 1.0])
    ax.set_yticks([0.0, 0.25, 0.5, 0.75, 1.0])

    ax.set_xlabel("Char-4gram Jaccard similarity")
    ax.set_ylabel("Embedding cosine similarity")

    # Title: left-aligned ABOVE the panel (not inside it). 10pt, bucket
    # color, includes n and Spearman rho so the panel interior stays clean.
    # Use fig.text in figure coords so it sits in the header region we
    # carved out by adding 0.3in to the figure height. The axes are
    # positioned to leave room above.
    fig.subplots_adjust(top=0.86)
    fig.text(0.005, 0.955,
             f"{BUCKET_LABEL[name]} (n={n}, $\\rho={rho:.2f}$)",
             ha="left", va="top",
             fontsize=10, color=color, fontweight="bold")

    fig.savefig(out_pdf, format="pdf")
    fig.savefig(out_png, format="png", dpi=300)
    plt.close(fig)
    return rho


# ---- Load data ----------------------------------------------------------
HERE = Path(__file__).resolve().parent
CSV_PATH = HERE / "emb_vs_lexical_scatter_data.csv"
rows = list(csv.DictReader(CSV_PATH.open()))

by_bucket: dict[str, list[tuple[float, float]]] = {k: [] for k in BUCKET_COLOR}
for r in rows:
    b = r["bucket"]
    if b not in by_bucket:
        continue
    by_bucket[b].append((float(r["char_4gram"]), float(r["emb_cos"])))

# ---- Emit one PDF per bucket --------------------------------------------
out_dir = HERE.parent / "out"
out_dir.mkdir(parents=True, exist_ok=True)

summary = []
for bucket in BUCKET_ORDER:
    pdf = out_dir / f"emb_vs_lexical_{bucket}.pdf"
    png = out_dir / f"emb_vs_lexical_{bucket}.png"
    rho = plot_bucket(bucket, BUCKET_COLOR[bucket], by_bucket[bucket], pdf, png)
    summary.append((bucket, len(by_bucket[bucket]), rho))
    print(f"wrote {pdf}")
    print(f"wrote {png}")

# ---- Cleanup old combined output ----------------------------------------
for stale in ("emb_vs_lexical_scatter.pdf", "emb_vs_lexical_scatter.png"):
    p = out_dir / stale
    if p.exists():
        p.unlink()
        print(f"removed stale {p}")

print("per-bucket summary:")
for bucket, n_b, rho_b in summary:
    print(f"  {bucket:14s} n={n_b:3d}  rho={rho_b:+.3f}")
