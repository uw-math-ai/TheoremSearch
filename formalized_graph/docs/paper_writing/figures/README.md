# Paper figures — agent guide

**If you are an agent (or future-Simon) about to make a figure, read this
file first, then read [`../figure_style.md`](../figure_style.md), then
write code.**

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

| figure | tool | purpose | source |
|---|---|---|---|
| `anchor_neighborhood` | TikZ | **§11 micro view** — one anchor + k=1 neighbors, dual-plane theme | [`src/anchor_neighborhood.tex`](./src/anchor_neighborhood.tex) |
| `anchor_neighborhood_mpl` | matplotlib | matplotlib fallback for the above (when no TeX toolchain available) | [`src/anchor_neighborhood.py`](./src/anchor_neighborhood.py) |
| `candidate_in_context` | mplot3d | **§11 macro view** — two-panel 3D, gold candidate spotlit against faded corpus, k=1 reach vs k=2 reach | [`src/candidate_in_context.py`](./src/candidate_in_context.py) |
| `emb_vs_lexical_both_correct` | matplotlib | **emb vs lexical, both-correct bucket** — single-column scatter, emb-cos vs char-4gram Jaccard for f$\to$i rank-1 gold pairs where both directions are rank-1 correct (n=121, $\rho{=}0.65$); high-emb cluster shows signal beyond surface overlap. Shared 0–1 axes with the other 3 bucket figures. [`out/emb_vs_lexical_both_correct.pdf`](./out/emb_vs_lexical_both_correct.pdf) | [`src/emb_vs_lexical_scatter.py`](./src/emb_vs_lexical_scatter.py) |
| `emb_vs_lexical_f2i_only` | matplotlib | **emb vs lexical, f$\to$i-only bucket** — single-column scatter, f$\to$i correct but i$\to$f wrong (n=98, $\rho{=}0.62$). Shared 0–1 axes. [`out/emb_vs_lexical_f2i_only.pdf`](./out/emb_vs_lexical_f2i_only.pdf) | [`src/emb_vs_lexical_scatter.py`](./src/emb_vs_lexical_scatter.py) |
| `emb_vs_lexical_i2f_only` | matplotlib | **emb vs lexical, i$\to$f-only bucket** — single-column scatter, i$\to$f correct but f$\to$i wrong (n=90, $\rho{=}0.67$). Shared 0–1 axes. [`out/emb_vs_lexical_i2f_only.pdf`](./out/emb_vs_lexical_i2f_only.pdf) | [`src/emb_vs_lexical_scatter.py`](./src/emb_vs_lexical_scatter.py) |
| `emb_vs_lexical_neither` | matplotlib | **emb vs lexical, neither bucket** — single-column scatter, neither direction rank-1 correct (n=191, $\rho{=}0.60$); low-emb / low-lex spread. Shared 0–1 axes. [`out/emb_vs_lexical_neither.pdf`](./out/emb_vs_lexical_neither.pdf) | [`src/emb_vs_lexical_scatter.py`](./src/emb_vs_lexical_scatter.py) |
| `ecosystem_overview` | matplotlib | **§1 / teaser** — Mathlib at center, 24 Lean project repos as a ring; area = stmt count (exp=0.42), overlap with Mathlib = fraction of project's outgoing `formal_dependency` edges that target Mathlib (range [0.68, 0.96]; min-max normalised then mapped to a half-tangent ↔ tangent band, so no project is fully nested), opacity = NL-graph mutual-rank-1 link strength, gold ring = top-5 most NL-linked projects (brownian-motion, pfr, carleson, FLT, toric) | [`src/ecosystem_overview.py`](./src/ecosystem_overview.py) |

Pattern these. The shared palette, plane semantics, status encoding,
and labeling conventions are in [`../figure_style.md`](../figure_style.md)
§11.

---

## How to add a new figure (checklist)

1. **Decide what the figure is selling in one sentence.** Write the
   caption first. If the caption is mushy, the figure will be too.
2. **Read [`../figure_style.md`](../figure_style.md) end-to-end.** Not
   skim. Especially §2 (palette), §5 or §6 (tool preamble), §7
   (anti-patterns), and §11 if the figure touches the informal ↔
   formal correspondence.
3. **Pick the tool by figure type:**
   - Graphs / pipelines / schema diagrams / Lean code listings →
     **TikZ** (`src/<name>.tex`).
   - Bar charts, scatters, line plots, heatmaps, anything driven by
     data → **matplotlib** (`src/<name>.py`).
   - Dense graphs (>20 nodes) or anything that genuinely needs 3D →
     **mplot3d** (`src/<name>.py`).
4. **Name the file by what it shows, not where it goes in the paper.**
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
8. **Compare against the style guide.** Walk down §7 (anti-patterns)
   line by line. Walk down §11 status table if dual-plane.
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
  the `rcParams` block from `figure_style.md` §5.
- **Committing `*.aux` / `*.log`.** The `.gitignore` in this dir
  handles it — but check `git status` before staging.

---

## How to invoke this from a fresh agent session

Copy-paste into a new Claude conversation:

> You are about to add a figure for the EMNLP paper. Before writing
> any code, read
> `formalized_graph/docs/paper_writing/figures/README.md` and then
> `formalized_graph/docs/paper_writing/figure_style.md`. Pattern an
> existing figure under `figures/src/`. Tool: {matplotlib | TikZ}.
> Content: <one-paragraph description>. End with the file path the
> PDF should write to and a one-line build command.

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
