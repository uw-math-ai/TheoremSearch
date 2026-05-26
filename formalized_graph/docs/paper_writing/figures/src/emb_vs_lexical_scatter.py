r"""Scatter: embedding cosine vs char-4gram Jaccard for f->i rank-1 gold pairs,
emitted as FOUR independent panels (one per bidirectional agreement bucket).

Per the LaTeX-first policy in `figure_style.md`, each PDF is a bare panel
with NO in-figure title text. A thin colored stripe sits along the top of
each panel in the bucket color so a reader scanning a 2x2 subfigure grid
can still tell the buckets apart at a glance. Bucket identity, n, and
Spearman rho live in the LaTeX `\subfigure` captions (see "Paper
integration" below), not in the image.

Shared 0-1 axes across all four PDFs make them mentally overlay-able.
Axis labels are kept on every panel; the LaTeX template author decides
whether to hide inner labels via the subfigure layout.

Data prep: /tmp/build_emb_vs_lexical.py (reproduces nl_corr's f2i seed=0
sample, attaches IDs and agreement bucket per pair). Cached snapshot at
`emb_vs_lexical_scatter_data.csv` next to this script.

Build:  python emb_vs_lexical_scatter.py
Outputs:
  ../out/emb_vs_lexical_both_correct.pdf  (+ .png)
  ../out/emb_vs_lexical_f2i_only.pdf      (+ .png)
  ../out/emb_vs_lexical_i2f_only.pdf      (+ .png)
  ../out/emb_vs_lexical_neither.pdf       (+ .png)

Paper integration
-----------------
Recommended LaTeX placement is a single 2x2 `\subfigure` block with one
unified caption that subsumes the four panels:

    \begin{figure}[t]
      \centering
      \subfigure[Both directions rank-1 correct (n=121, $\rho=0.65$)]
        {\includegraphics[width=.46\linewidth]{figures/out/emb_vs_lexical_both_correct.pdf}}
      \subfigure[Only formal$\to$informal correct (n=98, $\rho=0.62$)]
        {\includegraphics[width=.46\linewidth]{figures/out/emb_vs_lexical_f2i_only.pdf}}\\
      \subfigure[Only informal$\to$formal correct (n=90, $\rho=0.67$)]
        {\includegraphics[width=.46\linewidth]{figures/out/emb_vs_lexical_i2f_only.pdf}}
      \subfigure[Neither direction rank-1 correct (n=191, $\rho=0.60$)]
        {\includegraphics[width=.46\linewidth]{figures/out/emb_vs_lexical_neither.pdf}}
      \caption{Embedding cosine vs. char-4gram Jaccard similarity for the
               500-pair f$\to$i rank-1 sample, split by which directions
               returned the gold partner at rank 1. Spearman $\rho$ within
               each bucket sits tightly around the overall 0.66 --- the
               embedding$\leftrightarrow$lexical relationship has the same
               slope across buckets; what shifts is the \emph{location} of
               the cloud.}
      \label{fig:emb-vs-lexical}
    \end{figure}
"""
from __future__ import annotations
import csv
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

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

# Single-column 4:3 base. No in-figure title -> no extra header height.
FIGSIZE_1COL = (3.3, 2.475)
SHARED_XLIM = (0.0, 1.0)
SHARED_YLIM = (0.0, 1.0)

# Color-band stripe along the top of the figure. Height is in figure
# fraction; at 2.475in tall, 0.018 ~= 3.2pt. Stripe spans the full figure
# width and sits flush against the top edge so it reads as a tab on the
# panel rather than as an axis decoration.
STRIPE_HEIGHT_FIG_FRAC = 0.018  # ~3.2pt at 2.475in figure height
STRIPE_LEFT_FIG_FRAC   = 0.0
STRIPE_WIDTH_FIG_FRAC  = 1.0


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

    # Thin bucket-color stripe along the top of the figure. Drawn in figure
    # coordinates as a Rectangle patch added to the figure (not the axes),
    # so it sits above the axes spine flush with the top edge. No text.
    stripe = Rectangle(
        (STRIPE_LEFT_FIG_FRAC, 1.0 - STRIPE_HEIGHT_FIG_FRAC),
        STRIPE_WIDTH_FIG_FRAC, STRIPE_HEIGHT_FIG_FRAC,
        transform=fig.transFigure,
        facecolor=color,
        edgecolor="none",
        zorder=10,
        clip_on=False,
    )
    fig.add_artist(stripe)

    # Leave a hair of room between the stripe and the axes top.
    fig.subplots_adjust(top=0.94)

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
