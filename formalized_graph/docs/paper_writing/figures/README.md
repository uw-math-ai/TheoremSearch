# Paper figures — agent guide

**If you are an agent (or future-Simon) about to make a figure, read this
file first, then read [`../figure_style.md`](../figure_style.md), then
write code.**

> **Most-important rule (see [`../figure_style.md`](../figure_style.md)
> §2 "LaTeX-first authoring"):** figures live inside a LaTeX paper. The
> **caption owns the prose**. The image carries only axis labels, data,
> and encoding annotations — no headlines, no n-counts, no $\rho$
> values, no "this figure shows…" interpretations inside the image.
> Draft the caption *before* you build the figure.

This directory is the only place paper-bound figures live. Everything
in here is reproducible from source — no Illustrator, no Figma, no
hand-tweaked PDFs.

---

## Layout

```
figures/
├── README.md             # this file — agent-facing checklist
├── .gitignore            # pdflatex byproducts
├── src/                  # source — every figure has a one-command rebuild
│   ├── <name>.tex        # TikZ standalone class
│   └── <name>.py         # matplotlib script
└── out/                  # rendered output, vector PDF (committed)
    ├── <name>.pdf
    └── <name>.png        # 300dpi raster for paste-into-Slack previews
```

**Commit both `src/` and `out/`.** PDFs are small; reviewers and us
three months from now need to confirm the figure matches the latest
data without rerunning everything.

---

## Existing figures (read these before adding a new one)

| figure | tool | `\label` | purpose | source |
|---|---|---|---|---|
| `anchor_neighborhood` | TikZ | `fig:anchor-neighborhood` | **§11 micro view** — one anchor + k=1 neighbors, dual-plane theme | [`src/anchor_neighborhood.tex`](./src/anchor_neighborhood.tex) |
| `anchor_neighborhood_mpl` | matplotlib | `fig:anchor-neighborhood-mpl` | matplotlib fallback for the above (when no TeX toolchain available) | [`src/anchor_neighborhood.py`](./src/anchor_neighborhood.py) |
| `candidate_in_context` | mplot3d | `fig:candidate-in-context` | **§11 macro view** — two-panel 3D, gold candidate spotlit against faded corpus, k=1 reach vs k=2 reach | [`src/candidate_in_context.py`](./src/candidate_in_context.py) |
| `emb_vs_lexical_both_correct` | matplotlib | `fig:emb-vs-lexical` (panel a) | **emb vs lexical, both-correct bucket** — panel of a 2$\times$2 LaTeX subfigure (`fig:emb-vs-lexical`); emb-cos vs char-4gram Jaccard for f$\to$i rank-1 gold pairs, both directions rank-1 correct (n=121, $\rho{=}0.65$). Bare panel, no in-figure title; green color-stripe identifies the bucket. Shared 0–1 axes across all four panels. [`out/emb_vs_lexical_both_correct.pdf`](./out/emb_vs_lexical_both_correct.pdf) | [`src/emb_vs_lexical_scatter.py`](./src/emb_vs_lexical_scatter.py) |
| `emb_vs_lexical_f2i_only` | matplotlib | `fig:emb-vs-lexical` (panel b) | **emb vs lexical, f$\to$i-only bucket** — panel of a 2$\times$2 LaTeX subfigure (`fig:emb-vs-lexical`); f$\to$i correct but i$\to$f wrong (n=98, $\rho{=}0.62$). Bare panel, blue color-stripe. Shared 0–1 axes. [`out/emb_vs_lexical_f2i_only.pdf`](./out/emb_vs_lexical_f2i_only.pdf) | [`src/emb_vs_lexical_scatter.py`](./src/emb_vs_lexical_scatter.py) |
| `emb_vs_lexical_i2f_only` | matplotlib | `fig:emb-vs-lexical` (panel c) | **emb vs lexical, i$\to$f-only bucket** — panel of a 2$\times$2 LaTeX subfigure (`fig:emb-vs-lexical`); i$\to$f correct but f$\to$i wrong (n=90, $\rho{=}0.67$). Bare panel, purple color-stripe. Shared 0–1 axes. [`out/emb_vs_lexical_i2f_only.pdf`](./out/emb_vs_lexical_i2f_only.pdf) | [`src/emb_vs_lexical_scatter.py`](./src/emb_vs_lexical_scatter.py) |
| `emb_vs_lexical_neither` | matplotlib | `fig:emb-vs-lexical` (panel d) | **emb vs lexical, neither bucket** — panel of a 2$\times$2 LaTeX subfigure (`fig:emb-vs-lexical`); neither direction rank-1 correct (n=191, $\rho{=}0.60$). Bare panel, red color-stripe. Shared 0–1 axes. [`out/emb_vs_lexical_neither.pdf`](./out/emb_vs_lexical_neither.pdf) | [`src/emb_vs_lexical_scatter.py`](./src/emb_vs_lexical_scatter.py) |
| `ecosystem_overview` | matplotlib | `fig:ecosystem-overview` | **§1 / teaser** — horizontal bar chart of the 24 non-Mathlib Lean Repo projects, sorted descending by count of mutual rank-1 NL$\leftrightarrow$FL pairs against the informal corpus. Bar length = statement count on a log x-axis (range 24–8,205); bar opacity is linear in NL-link count (floor 0.30). All bars use `ACCENT_PURPLE` with a thin 0.3pt outline (no special top-5 treatment). A `BLUE_PRIMARY` Mathlib scale-anchor bar (alpha 0.20, 351,397 statements) sits above a thin horizontal rule, showing the scale gap between Mathlib and the rest of the ecosystem on the same axis. Per-bar `NL <count>` labels in gray to the right. | [`src/ecosystem_overview.py`](./src/ecosystem_overview.py) |
| `matching_pipeline` | TikZ | `fig:matching-pipeline` | **§4.1 matching pipeline** — two-arm symmetric NL$\leftrightarrow$FL pipeline on one real corpus pair (PFR Lemma 2.17 / `ProbabilityTheory.measureMutualInfo_nonneg`). Each arm is a four-stage *vertical* pipeline: `source artifact → extracted statement → slogan (qwen3-235b) → embedding (qwen3-8b, dim 4096)`. The informal arm (pastel red) starts from an arXiv paper / blueprint; the formal arm (pastel blue) starts from a Lean project (Mathlib community). The two embeddings render as tall 4096-dim column vectors with `\vdots` in the middle and converge into a purple cosine-similarity operator on the figure's vertical center line, which emits the score $0.974$ and a green "strong match" verdict ($\geq 0.95$). Logos above each pipeline stage identify the source / model: arXiv above the paper box, Mathlib above the Lean-project box, Qwen above each model-driven arrow. The two arms are arranged in a V / wineglass — boxes shift monotonically inward as the pipeline descends — so the convergence point at the green cosine disk is visually telegraphed. Items marked `*` on operator labels are configurable models (qwen3-235b for slogan generation, qwen3-8b for embedding). | [`src/matching_pipeline.tex`](./src/matching_pipeline.tex) |

Pattern these. The shared palette, plane semantics, status encoding,
and labeling conventions are in [`../figure_style.md`](../figure_style.md)
§13.

---

## How to add a new figure (checklist)

1. **Decide what the figure is selling in one sentence.** Write the
   caption first. If the caption is mushy, the figure will be too.
1.5. **Draft the caption + suggested `\label{}` BEFORE building the
   figure, in two places.** If you can't write the caption, you don't
   know what the figure is selling yet. The caption is the figure's
   contract with the paper body; every design choice in the image
   should serve it. (See `figure_style.md` §2 "LaTeX-first
   authoring.")
   - **Place 1 — script docstring.** Put the draft caption inside the
     script's module docstring under a `Paper integration:` block,
     with the full `\begin{figure}…\end{figure}` LaTeX so an agent
     reading the script alone knows the figure's contract.
     `candidate_in_context.py` is the reference shape.
   - **Place 2 — this README's "Paper LaTeX integration" section
     below.** Add a section per `\label`. When you ship the figure
     in the same commit, the docstring and README stay in sync.
   - If they ever drift, the README wins (it's what the paper actually
     pulls from).
2. **Read [`../figure_style.md`](../figure_style.md) end-to-end.** Not
   skim. Especially §2 (LaTeX-first authoring), §2.5 (encoding
   principles + channel ranking — one variable per channel),
   §3 (palette), §6 or §7 (tool preamble), §8 (encoding patterns),
   §9 (anti-patterns), and §13 if the figure touches the informal ↔
   formal correspondence.
3. **Pick the tool by figure type:**
   - Graphs / pipelines / schema diagrams / Lean code listings →
     **TikZ** (`src/<name>.tex`).
   - Bar charts, scatters, line plots, heatmaps, anything driven by
     data → **matplotlib** (`src/<name>.py`).
   - Dense graphs (>20 nodes) or anything that genuinely needs 3D →
     **mplot3d** (`src/<name>.py`).
4.5. **If your figure is a pipeline/process diagram, also read §8.5 in
   `figure_style.md`.** The six patterns there (operator-label placement,
   `*` annotation, semantic notation, convergence semantics, symmetric
   arms, dashed-pastel box recipe) are easy to get wrong and hard to fix
   after the figure is built.
5. **Name the file by what it shows, not where it goes in the paper.**
   `cycle_consistency_lift.py`, not `figure_3.py`. Figure numbers
   change; meanings don't.
5. **Copy a sibling figure** and modify, rather than starting blank.
   The palette tokens, `rcParams` block, and plane styles are
   load-bearing.
6. **Build it.** From `src/`:
   ```
   python <name>.py                                    # matplotlib
   pdflatex -output-directory=../out <name>.tex        # TikZ
   ```
   Both write the PDF to `../out/<name>.pdf`.
7. **Open the PDF and look at it.** Tool output succeeding ≠ figure
   correct. Check: are the labels colliding? Is the legend in the
   corner? Does the headline number pop? Is anything truncated?
8. **Walk the §9.5 pre-ship rubric** (7 yes/no questions, ~30 seconds).
   Also walk §9 (anti-patterns) line by line and §13 status table if
   dual-plane. If any §9.5 question is *no*, fix before saving.
9. **Commit `src/` and `out/`.** Update the table above if the figure
   is paper-bound. If you added a new convention, update
   `../figure_style.md` in the same commit.

---

## Common pitfalls (every agent has hit at least one of these)

- **Raw LaTeX strings in matplotlib without `usetex=True`.** A label
  like `r"\texttt{\textbackslash lean\{\}}"` renders as literal source
  text. Either enable usetex or write plain `\lean{}` and set
  `family="monospace"`.
- **Missing Unicode glyphs** (e.g. `●`, `○`, `→` in Helvetica). You'll
  see `UserWarning: Glyph N missing from font`. Replace with proper
  matplotlib markers (`ax.scatter(...)`) or LaTeX math (`r"$\to$"`).
- **mplot3d `depthshade=True` on highlighted markers.** Defaults to
  True; dims your foreground based on z-depth, defeating the
  highlight. Set `depthshade=False` on every spotlit scatter.
- **mplot3d text positioning.** `ax.text(x, y, z, ...)` sits at the
  projected screen position of `(x, y, z)`. You can't offset it
  cleanly in screen coords. Use a leader line (`Arrow3D` subclass in
  `candidate_in_context.py`) + text at an offset 3D position.
- **No `bbox` on labels that overlap nodes/edges.** Faded background
  bleeds through and shreds readability. Always
  `bbox=dict(facecolor="white", edgecolor=GRAY_RULE, linewidth=0.4,
  boxstyle="round,pad=0.24", alpha=0.95)`.
- **Auto-selecting candidates / anchors from synthetic clustered
  data.** Euclidean-nearest k=1 neighbors clump up — the fan-out
  doesn't read. Hand-pin highlighted regions at `CENTER`.
- **`plt.tight_layout()` + `savefig(bbox_inches='tight')` together.**
  Pick one. Prefer `bbox_inches='tight'` via `rcParams`.
- **`fig.suptitle` or `ax.set_title`.** The caption is the title.
  Don't waste vertical space.
- **Default `tab:blue` blue / default DejaVu Sans / default
  matplotlib spine box.** All three scream "homework." Always load
  the `rcParams` block from `figure_style.md` §6.
- **Paper-facing prose inside the image** (titles, headlines,
  `n = N`, `$\rho = X$`, "this figure shows…"). We discovered this
  iteratively across the scatter and ecosystem figures; the policy
  is now in `figure_style.md` §2 "LaTeX-first authoring." Captions
  own the prose; images carry data and encoding.
- **Operator labels floating in white space.** A common trap: the model
  or operator name ends up centered between the two arms of a pipeline
  (or off to the side), disconnected from any arrow. The reader can't
  tell which transformation it belongs to. Fix: move the label onto the
  arrow — above it for the top arm, below it for the bottom arm. See
  §8.5.1 in `figure_style.md` and the full §8.5 pattern set.
- **Committing `*.aux` / `*.log`.** The `.gitignore` in this dir
  handles it — but check `git status` before staging.

---

## How to invoke this from a fresh agent session

Copy-paste into a new Claude conversation:

> You are about to add a figure for the EMNLP paper. Read
> `formalized_graph/docs/paper_writing/figures/README.md` then
> `formalized_graph/docs/paper_writing/figure_style.md`. Draft the
> LaTeX caption + `\label{}` BEFORE writing code (§2 LaTeX-first);
> ground every design choice in §2.5 (encoding principles + channel
> ranking — one variable per channel). Tool: {matplotlib | TikZ}.
> Content: <one-sentence description>. Pattern a sibling in
> `figures/src/`. Walk the §9.5 pre-ship rubric (7 yes/no questions)
> before saving. End with the file path the PDF should write to and a
> one-line build command.

### Iteration discipline

- **Read the rendered PNG with the `Read` tool after every build.** Tool success ≠ visually correct. Labels collide, boxes truncate, convergence happens at the wrong stage — none of these are caught by a clean `pdflatex` exit code.
- **One specific nit per round, not "make it better."** Vague feedback produces vague changes. Name the exact node, label, or coordinate that needs moving.
- **2 iterations max per dispatch.** Beyond that, re-scope the task: the design needs rethinking, not more tweaking.
- **Model selection:** Sonnet 4.6 for mechanical layout iteration (read PNG → tweak coordinates → rebuild). Opus 4.7 for design exploration (generate 3 candidate variants, compare, choose).

---

## Paper LaTeX integration

For each paper-bound figure, a draft caption, suggested `\label{}`, and
suggested placement. Captions are drafts — revise for the final paper.
The four `emb_vs_lexical_*` panels are composed into a single 2×2
`\subfigure` block under one unified caption and `\label`.

### fig:emb-vs-lexical (`emb_vs_lexical_{both_correct,f2i_only,i2f_only,neither}.pdf`)

**Suggested label:** `fig:emb-vs-lexical`
**Suggested placement:** §4.2 (Bidirectional retrieval results), as a 2×2 `\subfigure` block next to the agreement-bucket table.

**Recommended LaTeX placement:** `\input` the production snippet at
[`out/emb_vs_lexical_grid.tex`](./out/emb_vs_lexical_grid.tex):

```latex
\input{figures/out/emb_vs_lexical_grid.tex}
```

The snippet is self-contained: it defines the four bucket colors
(`groupGreen` / `groupBlue` / `groupPurple` / `groupRed`), defines a
robust `\dotmark{<color>}` command that renders a small filled TikZ
disc inline, and emits the `\begin{figure}...\end{figure}` block with a
2$\times$2 `\subcaptionbox` layout and hairline (0.4pt, 28%-gray)
row/column separator rules. The unified caption uses inline
`\dotmark{...}` circles in the four bucket colors to key the panels to
direction-correctness buckets, and reports per-bucket $n$ and Spearman
$\rho$. Final `\label` is `fig:emb-vs-lexical`; sub-labels are
`fig:emb-vs-lexical-{both,f2i,i2f,neither}`.

Required preamble in the main paper:

```latex
\usepackage{tikz}
\usepackage{subcaption}
\usepackage{xcolor}
\usepackage{colortbl}   % needed for \arrayrulecolor on the separator rules
\usepackage{graphicx}
```

A rendered preview of the snippet (compiled standalone against the
panel PDFs already in `out/`) lives at
[`out/emb_vs_lexical_grid_preview.pdf`](./out/emb_vs_lexical_grid_preview.pdf)
for eyeballing the layout without rebuilding.

Each panel PDF is a bare scatter with no in-figure title; a thin
bucket-colored stripe along the top edge (~3.2pt tall, full panel width)
identifies the bucket when the four panels sit side-by-side. Panel
order follows `BUCKET_ORDER` in `src/emb_vs_lexical_scatter.py`
(both_correct, f2i_only, i2f_only, neither) and the bucket→color map is
green / blue / purple / red.

### fig:ecosystem-overview (`ecosystem_overview.pdf`)

**Suggested label:** `fig:ecosystem-overview`
**Suggested placement:** §1 (teaser) or §3 (corpus).
**Caption draft:**

```latex
\begin{figure}[t]
  \centering
  \includegraphics[width=\linewidth]{figures/out/ecosystem_overview.pdf}
  \caption{The 24 non-Mathlib Lean Repo projects, ranked by their count
           of mutual rank-1 NL$\leftrightarrow$FL pairs against the
           informal corpus (right of each bar). Bar length is statement
           count (log scale, range 24--8{,}205); bar opacity is linear in
           NL-link count. The Mathlib anchor at the top (351{,}397
           statements) sits on the same axis, showing the scale gap
           between Mathlib and the rest of the ecosystem. Eleven of the
           24 projects have zero mutual rank-1 NL pairs --- variation in
           informal-graph linkage, not raw size, is the salient axis.
           Per-project numbers in Table~\ref{tab:ecosystem-overview}.}
  \label{fig:ecosystem-overview}
\end{figure}
```

### fig:matching-pipeline (`matching_pipeline.pdf` / `matching_pipeline_horizontal.pdf`)

**Suggested label:** `fig:matching-pipeline`
**Suggested placement:** §4.1 (matching pipeline) — first figure of the
methods section, or §3 (corpus) if used as a teaser. Likely wants
`figure*` (two-column wide) given the horizontal layout.
**Caption draft:**

```latex
\begin{figure*}[t]
  \centering
  \includegraphics[width=\linewidth]{figures/out/matching_pipeline_horizontal.pdf}
  \caption{Bidirectional NL$\leftrightarrow$formal-Lean matching on one
           real corpus pair (PFR blueprint Lemma 2.17 paired with
           \texttt{ProbabilityTheory.measureMutualInfo\_nonneg}). Each
           arm is a four-stage pipeline: source artifact (an arXiv
           paper / blueprint on the informal row, a Lean project on the
           formal row) $\to$ extracted theorem statement (LaTeX / Lean
           source) $\to$ one-sentence slogan $\to$ 4096-dim embedding.
           The two embeddings meet at a cosine-similarity operator on
           the right; here the score is $0.974$, well above the $0.95$
           strong-match threshold. The slogan is the shared interlingua;
           embeddings live in a common space, so the same pipeline runs
           informal$\to$formal and formal$\to$informal without
           retraining. Items marked \texttt{*} are configurable models
           (\texttt{qwen3-235b} for slogan generation,
           \texttt{qwen3-8b} for embedding; defaults shown).}
  \label{fig:matching-pipeline}
\end{figure*}
```

### fig:candidate-in-context (`candidate_in_context.pdf`)

**Suggested label:** `fig:candidate-in-context`
**Suggested placement:** §11 (formalization candidate selection / dual-plane macro view).
**Caption draft:**

> Macro view of a candidate formalization target (gold) and its k=1
> reach (saturated) vs. k=2 reach (faded) across the dual-plane
> informal/formal dependency graphs. Background nodes are the
> surrounding corpus scaled to ~60+55 nodes per plane; node area is
> constant within plane. Panel (a): k=1 reach — the candidate has an
> immediately formalized informal neighbor and the "graph pack" of
> formal partners (green dashed `\lean{}` matches) sits directly
> below the candidate column. Panel (b): k=2 reach — every k=1
> neighbor is unformalized, so the closest formalized informal node
> is k=2 away and the vertical match line lives off-axis from the
> candidate column. The empty buffer between the spotlit cluster and
> the corpus illustrates the locality of the embedding-based
> retrieval and motivates the neighborhood-radius parameter in §11's
> candidate scoring.

### `anchor_neighborhood` / `anchor_neighborhood_mpl`

May not be in the final paper — currently a §11 conceptual / pedagogical
companion to `candidate_in_context`. If kept, suggested label
`fig:anchor-neighborhood` and placement §11 (introducing the dual-plane
theme on a single anchor before the macro view in
Fig.~\ref{fig:candidate-in-context}). Caption deferred until the §11
narrative is settled.

---

## When in doubt

- The style guide is prescriptive. If it conflicts with what looks
  right to you, **the style guide wins** — consistency across figures
  beats local prettiness. If you genuinely think it should change,
  update `figure_style.md` in the same commit as the figure and say
  why in the commit message.
- Existing figures are the second source of truth. If something isn't
  written down but every figure does it, do it.
- Ask before adding a new color, a new convention, or a new figure
  type — these are paper-wide decisions.
