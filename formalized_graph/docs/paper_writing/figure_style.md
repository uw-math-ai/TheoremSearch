# Figure Style Guide

This file is the **specification an emitter (human, Claude, or other model)
must follow when producing a figure for the EMNLP paper.** It is
prescriptive, not descriptive.

Two consumers:
1. **Claude → TikZ/LaTeX** for diagrams (pipelines, graphs, schema,
   agent loops, code listings with callouts).
2. **Claude → matplotlib/Python** for charts (bars, scatters, line
   plots with CI bands, heatmaps).

Both must produce **vector PDF** that drops into the paper unchanged.
No raster except screenshots.

---

## 1. Genre grounding

Surveyed for visual conventions (full report in agent run 2026-05-25):

| paper | what we take from it |
|---|---|
| Prior in-house paper (arXiv:2602.05216) | pastel-box pipelines, red/blue-coded table numbers, axis-free scatters with Tableau categorical palette |
| LeanSearch v2 (arXiv:2605.13137) | TikZ pipeline with a *single* accent color (red dashed) to mark feedback edges |
| Lean Finder (arXiv:2510.15940) | matplotlib bar/scatter, headline number highlighted in accent color, ICLR-clean |
| Herald (arXiv:2410.10878) | grayscale + one accent, results carried by tables |
| DeepSeek-Prover-V1.5 (arXiv:2408.08152) | ±σ shaded bands on line plots — the gold standard for uncertainty viz |
| LeanDojo / ReProver (arXiv:2306.15626) | Lean code listings with boxed callouts, multi-panel teaser fig |

**Modal genre style:** Tufte-minimal, blue-dominant, low figure count
(3–5 mains), TikZ-for-diagrams + matplotlib-for-plots, sparing accent
for semantic emphasis.

**Where the in-house style departs from modal:** softer/pastel palette
in pipelines, red/blue-coded table numbers, more decorative use of
external logos (arXiv, DeepSeek, Qwen icons in Fig 1). We keep this —
it's the established brand.

---

## 2. Palette (hex codes — use these literally)

### Primary palette (process / structure)

| token | hex | use |
|---|---|---|
| `BLUE_PRIMARY`   | `#2E5C8A` | process boxes, plot lines, "ours" |
| `BLUE_SOFT`      | `#A8C5E0` | pastel pipeline boxes (matches prior paper Fig 1) |
| `GRAY_TEXT`      | `#2A2A2A` | all text inside figures |
| `GRAY_RULE`      | `#999999` | spines, axes, light arrows |
| `GRAY_BG`        | `#F2F2F2` | optional figure background fill (use sparingly) |

### Accent palette (semantic emphasis)

| token | hex | use |
|---|---|---|
| `ACCENT_RED`     | `#C8553D` | the *one* thing that's different (feedback edge, "wrong", error case) |
| `ACCENT_ORANGE`  | `#E89F50` | partial / annotated-only / warning state |
| `ACCENT_GREEN`   | `#5B8C5A` | success / resolved / passed |
| `ACCENT_GOLD`    | `#C9A227` | **candidate (unformalized target)** — the node the figure is "selling" |
| `GOLD_DARK`      | `#8C7019` | edge / stroke / label color for gold candidate markers |
| `ACCENT_PURPLE`  | `#7E5B9E` | embeddings, similarity, semantic space |

### Categorical palette (3+ classes — use in this exact order)

```
1. #2E5C8A  (deep blue)
2. #C8553D  (rust red)
3. #5B8C5A  (sage green)
4. #E89F50  (amber)
5. #7E5B9E  (purple)
6. #4A6FA5  (steel blue)
7. #B8743D  (burnt orange)
8. #888888  (gray for "other")
```

Source: muted Tableau-10 + ColorBrewer Set2 blend. Colorblind-safe
(checked against deuteranopia and protanopia simulators). Prints
legibly in grayscale.

**Never use:** `jet`, `hsv`, `rainbow`, `viridis` for categorical data
(viridis is fine for *ordinal* heatmaps), pure black `#000`, pure red
`#FF0000`, default matplotlib `tab:blue` blue.

### Color semantics — formalization-status convention (project-specific)

When showing the formalization graph (every figure in the paper that
touches `formalization_candidate_neighborhood` or smoke-test data),
use this **fixed mapping**:

| status | color | hex |
|---|---|---|
| `resolved` (linked to existing Lean decl) | `ACCENT_GREEN` | `#5B8C5A` |
| `annotated_only` (`\lean{}` present but doesn't resolve) | `ACCENT_ORANGE` | `#E89F50` |
| `matched_only` (embedding match only, no annotation) | `ACCENT_PURPLE` | `#7E5B9E` |
| `none` (unformalized, the target population) | `ACCENT_RED` | `#C8553D` |
| anchor / center node | `BLUE_PRIMARY` (filled) | `#2E5C8A` |
| **candidate** (the spotlit unformalized target in dual-plane figures — see §11) | `ACCENT_GOLD` (filled, `GOLD_DARK` edge) | `#C9A227` |

Use across all figures touching the formalization graph so a reader
who's seen one figure can read the next without re-checking the legend.

---

## 3. Typography

- **In-figure text: Helvetica or Arial, never Computer Modern.**
  Reason: CM inside a plot reads as a 1995 thesis. Sans-serif inside
  figures is the modal choice across every paper surveyed.
- **Body text remains CM** (the paper's class file handles this; don't
  touch).
- **Sizes** (final on-page size, after `\includegraphics` scaling):
  - tick labels: 8 pt
  - axis labels: 9 pt
  - legends: 9 pt (no frame, `frameon=False`)
  - node labels in diagrams: 9 pt
  - figure title (only when needed; prefer caption): 10 pt
- **Math inside figures:** use LaTeX math via matplotlib's `usetex=True`
  or TikZ native. Don't render math as unicode glyphs.
- **Lean code inside figures:** monospace (Inconsolata or Source Code
  Pro), 8 pt, with `listings` minimal coloring: keywords bold-black,
  identifiers `BLUE_PRIMARY`, comments `GRAY_RULE` italic, strings
  `ACCENT_GREEN`.

---

## 4. Layout & sizing

- **Single-column figure width:** 3.3 in (≈ 240 pt, EMNLP/ACL one-column).
- **Two-column figure width:** 7.0 in (≈ 505 pt). Use only when content
  genuinely needs the width.
- **Aspect ratio:** 4:3 for charts; free for diagrams (let content dictate).
- **Output format:** PDF (vector) for everything except screenshots
  (PNG, 300 dpi minimum).
- **Margins inside figure:** `bbox_inches='tight'` + 2 pt padding. Don't
  ship matplotlib's default white border.
- **Caption goes below figure**, in CM 9 pt italic per the EMNLP class.
  Caption is part of the figure — write it concisely and self-contained
  (a reader scanning only figures should understand the claim).

---

## 5. matplotlib recipe (drop-in preamble)

Put this at the top of every plotting script. Anything that emits a
figure for the paper must run this first.

```python
import matplotlib as mpl
import matplotlib.pyplot as plt

# ---- Palette (must match figure_style.md §2) -----------------------------
PALETTE = {
    "blue_primary":  "#2E5C8A",
    "blue_soft":     "#A8C5E0",
    "gray_text":     "#2A2A2A",
    "gray_rule":     "#999999",
    "gray_bg":       "#F2F2F2",
    "accent_red":    "#C8553D",
    "accent_orange": "#E89F50",
    "accent_green":  "#5B8C5A",
    "accent_purple": "#7E5B9E",
}
CATEGORICAL = ["#2E5C8A", "#C8553D", "#5B8C5A", "#E89F50",
               "#7E5B9E", "#4A6FA5", "#B8743D", "#888888"]
STATUS_COLOR = {  # formalization-status convention (§2)
    "resolved":        PALETTE["accent_green"],
    "annotated_only":  PALETTE["accent_orange"],
    "matched_only":    PALETTE["accent_purple"],
    "none":            PALETTE["accent_red"],
    "anchor":          PALETTE["blue_primary"],
}

# ---- rcParams -----------------------------------------------------------
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
    "axes.edgecolor":     PALETTE["gray_rule"],
    "axes.linewidth":     0.8,
    "axes.spines.top":    False,
    "axes.spines.right":  False,
    "axes.labelcolor":    PALETTE["gray_text"],
    "xtick.color":        PALETTE["gray_text"],
    "ytick.color":        PALETTE["gray_text"],
    "xtick.direction":    "out",
    "ytick.direction":    "out",
    "xtick.major.size":   3,
    "ytick.major.size":   3,
    "grid.color":         PALETTE["gray_rule"],
    "grid.linewidth":     0.5,
    "grid.alpha":         0.3,
    "axes.grid.axis":     "y",
    "lines.linewidth":    1.4,
    "lines.markersize":   5,
    "axes.prop_cycle":    mpl.cycler(color=CATEGORICAL),
    "figure.dpi":         150,           # display only
    "savefig.dpi":        300,           # raster fallback
    "savefig.format":     "pdf",
    "savefig.bbox":       "tight",
    "savefig.pad_inches": 0.02,
    "pdf.fonttype":       42,            # editable text in vector PDF
    "ps.fonttype":        42,
})

# ---- Standard figure sizes ----------------------------------------------
FIGSIZE_1COL = (3.3, 2.5)   # EMNLP single-column
FIGSIZE_2COL = (7.0, 3.5)   # EMNLP double-column
```

### matplotlib idioms (always)

- **Always** add `±σ` band on line plots: `ax.fill_between(x, m-s, m+s, alpha=0.2, color=...)` (DeepSeek-Prover convention).
- **Always** print bar values on top of bars for headline figures: `ax.text(x, y+0.5, f"{y:.1f}", ha="center", fontsize=8)`.
- **Always** use `ax.legend(loc="best", frameon=False, handletextpad=0.4)`.
- **Never** call `plt.tight_layout()` and `savefig(bbox_inches='tight')` together — pick one (prefer `bbox_inches='tight'` via rcParams).
- **Never** add a figure-level title (`fig.suptitle`); the caption is the title.
- **Never** leave default matplotlib labels (`x`, `y`); always set or remove.

---

## 6. TikZ recipe (drop-in preamble)

Add to the paper's preamble; reuse styles across every TikZ figure.

```latex
\usepackage{tikz}
\usetikzlibrary{positioning,arrows.meta,calc,shapes.geometric,fit,backgrounds}

% --- Palette (must match figure_style.md §2) -----------------------------
\definecolor{BluePrimary}{HTML}{2E5C8A}
\definecolor{BlueSoft}{HTML}{A8C5E0}
\definecolor{GrayText}{HTML}{2A2A2A}
\definecolor{GrayRule}{HTML}{999999}
\definecolor{GrayBG}{HTML}{F2F2F2}
\definecolor{AccentRed}{HTML}{C8553D}
\definecolor{AccentOrange}{HTML}{E89F50}
\definecolor{AccentGreen}{HTML}{5B8C5A}
\definecolor{AccentPurple}{HTML}{7E5B9E}

% --- Reusable styles -----------------------------------------------------
\tikzset{
  every node/.style       = {font=\sffamily\small, text=GrayText},
  procbox/.style          = {rectangle, rounded corners=2pt, draw=GrayRule,
                             line width=0.5pt, fill=BlueSoft, minimum height=7mm,
                             minimum width=18mm, inner sep=4pt, align=center},
  accentbox/.style        = {procbox, fill=AccentOrange!30, draw=AccentOrange},
  errorbox/.style         = {procbox, fill=AccentRed!20,    draw=AccentRed},
  successbox/.style       = {procbox, fill=AccentGreen!20,  draw=AccentGreen},
  arr/.style              = {-{Latex[length=2mm]}, line width=0.8pt, draw=GrayText},
  arrdashed/.style        = {arr, dashed, draw=AccentRed},
  arrfeedback/.style      = {arrdashed, bend left=20},
  % graph-node styles for formalization status (§2 convention)
  node_resolved/.style    = {circle, draw=AccentGreen,  fill=AccentGreen!20,
                             line width=0.8pt, minimum size=6mm, inner sep=1pt,
                             font=\sffamily\scriptsize},
  node_annotated/.style   = {node_resolved, draw=AccentOrange, fill=AccentOrange!20},
  node_matched/.style     = {node_resolved, draw=AccentPurple, fill=AccentPurple!20},
  node_none/.style        = {node_resolved, draw=AccentRed,    fill=AccentRed!20},
  node_anchor/.style      = {circle, draw=BluePrimary, fill=BluePrimary,
                             text=white, line width=1pt, minimum size=9mm,
                             font=\sffamily\bfseries\scriptsize},
  edge_dep/.style         = {-, line width=0.4pt, draw=GrayRule},
  edge_dep_k2/.style      = {edge_dep, dashed},
}
```

### TikZ idioms (always)

- **Direction:** left-to-right for pipelines, radial for neighborhoods,
  top-down only when hierarchy is the point.
- **Boxes:** `procbox` for default, `accentbox`/`errorbox`/`successbox`
  for semantic emphasis. Never more than one accent per figure.
- **Arrows:** solid `arr` for normal flow, `arrdashed` for feedback /
  optional / "happens later". Reserve dashed-red for the *one* thing
  that's different.
- **Labels on edges:** above the edge, `font=\sffamily\scriptsize`, no
  background fill unless edges cross.
- **Always** wrap figure in `\begin{figure}[t] ... \centering ... \caption{...} \label{fig:...} \end{figure}`. The `[t]` placement matches the paper's class file.

---

## 7. Anti-patterns (do not ship a figure with any of these)

| ✗ | why |
|---|---|
| Rainbow / jet / hsv colormap | reads as undergrad |
| 3D bars, 3D pies, drop shadows, gradients | nothing in this genre uses them |
| Default `plt.plot()` with no rcParam overrides | DejaVu Sans + full spine box screams "homework" |
| Mixed serif/sans inside one figure | pick one (sans inside, serif outside) |
| Raster (PNG/JPG) for line art | vector PDF, always — PNG only for UI screenshots |
| Legend inside the plot area with a frame box | `frameon=False`, place above or right |
| Default matplotlib title (`ax.set_title`) | caption is the title; titles waste vertical space |
| More than one accent color per figure | dilutes the semantic signal |
| > 8 categories without grouping | collapse the long tail into "other" (`#888888`) |
| Unlabeled axes ("just look at the legend") | every axis labeled with units |
| No CI / error bars on multi-sample results | required after the multi-seed work — use ±σ band or 95% CI ticks |

---

## 8. How to invoke this guide when prompting Claude

When asking Claude to emit a figure, paste this short brief:

> Emit a paper-grade figure following
> `formalized_graph/docs/paper_writing/figure_style.md`.
> Tool: **{matplotlib | TikZ}**.
> Width: **{1col=3.3in | 2col=7.0in}**.
> Content: <one-paragraph description of what to show>.
> Use the palette tokens (`BLUE_PRIMARY`, `ACCENT_GREEN`, etc.) as named
> constants in the code. For status colors, follow the §2 formalization
> mapping. End with the file path the PDF should write to.

Claude must respond with the full code + a one-line `make` / `pdflatex`
/ `python -m` invocation to render it. No prose narration in the
response — code-only.

---

## 9. File-system conventions for figures

```
formalized_graph/docs/paper_writing/
├── figure_style.md              # this file
└── figures/
    ├── src/
    │   ├── <name>.tex           # TikZ source (standalone class)
    │   └── <name>.py            # matplotlib source
    └── out/
        └── <name>.pdf           # rendered output
```

- Source files live under `figures/src/`. Reproducible: every figure has
  a one-command rebuild (`pdflatex <name>.tex` or `python <name>.py`).
- Rendered PDFs go to `figures/out/` and are referenced from the paper
  with `\includegraphics{figures/out/<name>.pdf}`.
- Both `src/` and `out/` are committed — PDFs are small for vector
  output, and reviewers (and us, three months later) need to verify
  the figure matches the latest data without rerunning everything.

---

## 10. Worked example

See [`figures/src/anchor_neighborhood.tex`](./figures/src/anchor_neighborhood.tex)
+ [`figures/src/anchor_neighborhood.py`](./figures/src/anchor_neighborhood.py)
for the canonical implementation of the §11 dual-plane theme — anchor
blueprint pair + neighborhood from `formalization_candidate_neighborhood`.
This is the test case that validates the guide.

---

## 11. Dual-plane theme (informal × formal)

**This is the recurring visual motif for any figure that needs to show
the informal and formal dependency graphs in relation to each other.**

Two tilted parallelogram "planes" stacked vertically with a slight 3D
shear:

- **Top plane (red, `AccentRed`):** informal dependency graph
  (blueprint LaTeX statements). Nodes are red. In-plane edges are
  faded red.
- **Bottom plane (blue, `BluePrimary`):** formal dependency graph
  (Lean declarations). Nodes are blue. In-plane edges are faded blue.
- **Vertical links (green dashed, `AccentGreen`):** blueprint
  `\lean{...}` annotations connecting an informal node to its formal
  partner. The *anchor pair* gets a thicker, solid-saturated green
  link; other formalized pairs get a thinner dashed green link.

### Status encoding within the informal plane

| visual | meaning |
|---|---|
| **gold-filled circle** (`ACCENT_GOLD` fill, `GOLD_DARK` edge) | **candidate** — the spotlit unformalized target the figure is "selling" |
| filled red circle (`inode`) | formalized informal node — has a `\lean{}`-resolved formal partner (and a green link down) |
| outlined red circle (`inode_unform`, thick border, light fill) | unformalized informal node — no formal partner |

The reader learns two visual cues at once: **(a) presence of a vertical
green link = "this is formalized,"** and **(b) outlined-vs-filled red
node = same information at a glance.** Use both so the figure reads
correctly even at small thumbnail size. Gold is reserved for the
single candidate the figure spotlights — it never appears in the
background population.

### Geometry constants (use literally for cross-figure consistency)

**TikZ micro view** (sheared parallelograms):
```
PlaneW = 7.4 cm        (or larger if needed)
Dx     = 1.5 cm        (depth shear in x)
Dy     = 0.95 cm       (depth shear in y, controls tilt steepness)
TopY   = 5.2 cm        (y-origin of informal plane)
BotY   = 0 cm          (y-origin of formal plane)
```
A node at plane-local `(u, v)` (`v ∈ [0, 1]` is depth, 0 = front,
1 = back) maps to world `(u + v*Dx, plane_y + v*Dy)`. Nodes that
appear in BOTH planes **must share their `(u, v)` so the vertical
link is truly vertical.**

**matplotlib macro view** (real mplot3d):
```
PLANE_W           = 10.0     (square plane edge in scene units)
HIGHLIGHT_RADIUS  = 2.8      (background-exclusion zone around CENTER)
Z_TOP, Z_BOT      = 4.0, 0.0 (plane heights)
view_init(elev=22, azim=-58) (tilt — slight, never top-down)
CENTER            = (5, 5)   (pin the highlighted region here)
K1_ANGLES         = [40, 130, 215, 305]  (degrees — k=1 fan-out)
K1_RADIUS         = 1.5       FL_RADIUS = 1.6
```
The **highlighted region is hand-pinned at `CENTER`** and **background
nodes are rejection-sampled** to stay outside `HIGHLIGHT_RADIUS`. Do
not auto-select the candidate from clustered data — Euclidean-nearest
k=1 neighbors always bunch up; you need fixed angles + radius to read
as a clear fan-out.

### Plane and node labels

- **Plane labels: title-cased, italic bold sans, in the plane's color**
  (`Informal Dependency Graph`, `Formal Dependency Graph (Lean)`).
  Placed **outside** the parallelograms (above the top plane, below
  the bottom plane). Never put the label inside — it always collides
  with a node sooner or later.
- **All node labels carry a white `bbox`** with a thin gray rule
  (`facecolor="white", edgecolor=GRAY_RULE, linewidth=0.4,
  boxstyle="round,pad=0.24", alpha=0.95`). Without the bbox, faded
  background nodes and edges show through and shred readability.
- **Candidate label** (macro view): bold `GOLD_DARK`, two lines —
  `candidate / (unformalized)` — placed upper-left of the candidate
  with an `Arrow3D` leader line.
- **Unformalized neighbors** (micro view): short bold red label
  (`unformalized`) to one side of the node.
- **Formalized k=1, k=2**: short gray label (`formalized k=1`,
  `formalized k=2 (further)`) — distance is the information the label
  is paying for.
- **Anchor pair** (micro view): italic green label
  `anchor: blueprint pair (\lean{})` placed left of the vertical anchor
  link, between the planes.
- **Legend always says "Blueprint match"** for the green dashed
  vertical link — not `NL↔FL match`, not `\lean{} link`. Reader-facing
  copy stays in the user's mental model.

### Reusable TikZ preamble (subset of §6)

The styles `inode`, `inode_unform`, `fnode`, `ianchor`, `fanchor`,
`iedge`, `fedge`, `blueprint`, `blueprint_anchor`, `plane_top`,
`plane_bot` should be **copied verbatim** into any new dual-plane
figure. Source: [`figures/src/anchor_neighborhood.tex`](./figures/src/anchor_neighborhood.tex).
When this convention is reused often enough we'll factor it out into
a shared `.tikzstyles` file; today, copy-paste is the cheaper path.

### When to use the dual-plane theme

- Any figure illustrating the **informal ↔ formal correspondence**
  (cycle-consistency story, bidirectional matching schematic,
  formalization-candidate selection, mutual rank-1 NN, etc.).
- Any figure showing **which Lean code "comes from" a given
  blueprint statement** or vice versa.
- **Not** for: pure-formal figures (e.g. f→f cross-project twins —
  one plane suffices), pure-informal figures (arXiv corpus stats),
  retrieval pipeline diagrams (use boxes + arrows per §6).

### Micro vs macro variant

The theme has two scales:

| variant | tool | nodes | when to use |
|---|---|---:|---|
| **micro** — [`anchor_neighborhood.tex`](./figures/src/anchor_neighborhood.tex) | TikZ | 5 informal + 3 formal | one anchor + its k=1 neighbors; conceptual / pedagogical figure that names every node |
| **macro** — [`candidate_in_context.py`](./figures/src/candidate_in_context.py) | matplotlib mplot3d | ~16 informal + ~13 formal background + spotlit highlights (synthetic) | corpus-scale "you are here" figure; one **gold candidate** spotlit against the rest of the corpus faded. Ships as a **two-panel** comparison: (a) candidate with a k=1 formalized neighbor, (b) candidate whose closest formalized neighbor is k=2 away. |

The macro view uses **real 3D** (`mpl_toolkits.mplot3d`,
`view_init(elev=22, azim=-58)`) because density would be unmanageable
in hand-drawn TikZ. The micro view stays in TikZ because it has ≤10
nodes and benefits from precise typographic control.

**Both use the same palette tokens, the same plane semantics
(red/top = informal, blue/bottom = formal, green dashed = blueprint
match), and the same node-status encoding (filled = formalized,
outlined = unformalized, gold = the spotlit candidate).** A reader
who's seen one should be able to read the other without re-checking
the legend.

For the macro view specifically:
- **Background is sparse and faded** (`N_NL≈16`, `N_FL≈13`,
  `alpha≈0.45` on nodes / `0.20` on edges). Background that's denser
  than that competes with the highlighted region for attention.
- **Hand-pin the highlighted region at `CENTER`** and reject background
  samples inside `HIGHLIGHT_RADIUS`. Auto-selecting a candidate from
  the synthetic clusters gives Euclidean-clumpy k=1 neighbors that
  don't read as a fan-out.
- **Place k=1 neighbors at fixed angles** (`K1_ANGLES = [40, 130, 215,
  305]`) so the fan-out star reads cleanly. FL pack positions follow
  the same angles + a small offset + jitter so the column looks
  organic rather than mechanical.
- **Highlighted nodes are 3–4× larger** than background scatter dots
  (`s≈95` vs `s≈28`). Candidate is the largest (`s≈300`) with
  `GOLD_DARK` edge.
- **Two-panel layout for contrast figures.** `fig.add_subplot(1, 2, N,
  projection="3d")` with one shared framed legend pinned at
  `(0.875, 0.755, 0.115, 0.225)` in figure coords. Sub-captions go via
  `fig.text(x, 0.04, "(a) ...")` below each panel. Each panel keeps
  its own plane labels via `ax.text2D`.
- **Use a 2D inset `Axes` for the legend.** Drawing legend markers in
  3D space gives them depth-shading and unpredictable positions; an
  inset stays put. Set its spines explicitly to `GRAY_RULE` /
  `linewidth=0.5` so the frame reads as intentional.
- **Use `Arrow3D` (subclassed `FancyArrowPatch`) for leader lines.**
  Plain text labels in mplot3d sit at the projected `(x,y,z)` of the
  marker — they cannot be offset cleanly in screen coords. A short
  leader line + offset text label (with white bbox) is the working
  idiom.
- **`depthshade=False` on every highlighted scatter call.** Otherwise
  mplot3d dims the foreground marker based on its z-depth — which
  defeats the point of highlighting it.

### Refactoring pattern (for new panels in this style)

`candidate_in_context.py` factors the drawing into:
`setup_axes(ax)`, `draw_background(ax, bg)`, `draw_candidate(ax)`,
`k1_position(angle)`, `draw_panel_k1(ax, bg)`, `draw_panel_k2(ax, bg)`.
Add a new scenario (e.g. cycle-consistency F→NL→F') by writing one
more `draw_panel_X(ax, bg)` function and a new `fig.add_subplot`. The
shared helpers guarantee the new panel uses the same palette,
geometry, and legend semantics as the others.
