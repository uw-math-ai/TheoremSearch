"""Scatter: embedding cosine vs char-4gram Jaccard for f->i rank-1 gold pairs,
colored by bidirectional agreement bucket.

Shows that the qwen3-8b embedding aligns with a lexical baseline
(Spearman rho ~ 0.66, n=500) but carries non-lexical signal in the
off-diagonal mass — high-emb low-lex matches sit in `both_correct`,
low-emb high-lex matches concentrate in `neither`/`f2i_only`.

Data prep: /tmp/build_emb_vs_lexical.py (reproduces nl_corr's f2i seed=0
sample, attaches IDs and agreement bucket per pair). Cached snapshot at
`emb_vs_lexical_scatter_data.csv` next to this script.

Build:  python emb_vs_lexical_scatter.py
Output: ../out/emb_vs_lexical_scatter.pdf  (+ .png)
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
    "both_correct": "both correct",
    "f2i_only":     "f$\\to$i only",
    "i2f_only":     "i$\\to$f only",
    "neither":      "neither",
}
# Draw order: smaller / informative classes last (on top).
BUCKET_ORDER = ["neither", "f2i_only", "i2f_only", "both_correct"]

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

FIGSIZE_1COL = (3.3, 2.5)


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

xs_all = [float(r["char_4gram"]) for r in rows]
ys_all = [float(r["emb_cos"]) for r in rows]
rho = _spearman(xs_all, ys_all)
n_total = len(rows)

# ---- Plot ---------------------------------------------------------------
fig, ax = plt.subplots(figsize=FIGSIZE_1COL)

for bucket in BUCKET_ORDER:
    pts = by_bucket[bucket]
    if not pts:
        continue
    xs, ys = zip(*pts)
    ax.scatter(xs, ys,
               s=17, alpha=0.55,
               c=BUCKET_COLOR[bucket], edgecolor="none",
               label=f"{BUCKET_LABEL[bucket]} (n={len(pts)})")

ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.set_xlabel("Char-4gram Jaccard similarity")
ax.set_ylabel("Embedding cosine similarity")
ax.set_xticks([0.0, 0.25, 0.5, 0.75, 1.0])
ax.set_yticks([0.0, 0.25, 0.5, 0.75, 1.0])

# Correlation annotation, top-left (legend goes bottom-right where data is sparse).
ax.text(0.03, 0.97,
        f"$\\rho = {rho:.2f}$, $n = {n_total}$",
        transform=ax.transAxes, ha="left", va="top",
        fontsize=8.5, color=PAL["gray_text"])

leg = ax.legend(loc="lower right", frameon=False,
                handletextpad=0.3, borderaxespad=0.2,
                labelspacing=0.25)

# ---- Save ---------------------------------------------------------------
out_dir = HERE.parent / "out"
out_dir.mkdir(parents=True, exist_ok=True)
pdf = out_dir / "emb_vs_lexical_scatter.pdf"
png = out_dir / "emb_vs_lexical_scatter.png"
fig.savefig(pdf, format="pdf")
fig.savefig(png, format="png", dpi=300)
print(f"wrote {pdf}")
print(f"wrote {png}")
