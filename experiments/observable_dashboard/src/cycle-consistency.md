---
title: "Cycle Consistency Pilot"
toc: true
---

# Cycle Consistency Pilot

Does providing formal-graph dependency context improve **cycle consistency** for
autoformalization? We ran a small paired experiment on 60 Mathlib declarations:
start from a real Lean 4 declaration **F**, generate an informal description **NL**,
then re-formalize NL under two conditions — **B (baseline)**: NL only; **T
(treatment)**: NL + the dependency context of F drawn from our formal graph.

```js
const d = FileAttachment("data/cycle_consistency.json").json();
```

```js
const s = d.summary;
const cands = d.candidates;
const strata = d.strata;
const editScatter = d.edit_scatter;
```

## 1. Headline Result

```js
display(html`<div style="display:flex;gap:24px;flex-wrap:wrap;margin:18px 0">
  ${[
    {label: "T preferred", val: s.t_count, pct: s.t_pct, color: "#2563eb"},
    {label: "B preferred", val: s.b_count, pct: s.b_pct, color: "#dc2626"},
    {label: "Tie",         val: s.tie_count, pct: s.tie_pct, color: "#6b7280"},
  ].map(({label, val, pct, color}) => html`
    <div style="flex:1;min-width:160px;padding:18px 22px;border-radius:10px;
                background:#f8fafc;border:1px solid #e2e8f0;text-align:center">
      <div style="font-size:42px;font-weight:700;color:${color}">${val}</div>
      <div style="font-size:14px;color:#64748b;margin-top:2px">${label}</div>
      <div style="font-size:22px;font-weight:600;margin-top:4px">${pct}%</div>
    </div>`)}
</div>
<div style="margin:8px 0 4px;font-size:13px;color:#475569">
  Wilcoxon signed-rank: W&nbsp;=&nbsp;${s.wilcoxon_stat},
  p&nbsp;≈&nbsp;${s.wilcoxon_p?.toExponential(1) ?? "—"}
  &nbsp;·&nbsp; n = ${s.n} candidates &nbsp;·&nbsp;
  treat as direction-finding, not a significance claim
</div>`);
```

Providing formal-graph dependency context is strongly preferred by the judge across
every stratum. Treatment candidates are also substantially closer to the original
signature by edit distance (mean **${s.edit_mean_T}** tokens vs. **${s.edit_mean_B}**
for baseline).

## 2. Stratified Preference

Candidates are stratified by **in-degree** (how widely the declaration is cited) and
**signature length**. The interaction of interest: does the graph help more for
dense, complex declarations where context is richest?

```js
{
  const indegOrder = ["dense", "medium", "non_dense"];
  const sizeOrder  = ["large", "small"];
  const allCells   = indegOrder.flatMap(i => sizeOrder.map(s => ({
    indeg: i, size: s, cell: `${i} × ${s}`
  })));

  display(Plot.plot({
    title: "Judge preference by stratum cell",
    marginLeft: 130,
    marginRight: 60,
    width,
    height: 260,
    x: {label: "Candidates", grid: true},
    y: {label: null, domain: allCells.map(c => c.cell)},
    color: {
      domain: ["T (treatment)", "tie", "B (baseline)"],
      range:  ["#2563eb", "#94a3b8", "#dc2626"],
      legend: true
    },
    marks: [
      Plot.barX(
        strata.flatMap(c => [
          {cell: c.cell, val: c.T,   cond: "T (treatment)"},
          {cell: c.cell, val: c.tie, cond: "tie"},
          {cell: c.cell, val: c.B,   cond: "B (baseline)"},
        ]),
        Plot.stackX({x: "val", y: "cell", fill: "cond", order: ["T (treatment)", "tie", "B (baseline)"], tip: true})
      ),
      Plot.text(
        strata.filter(c => c.T > 0),
        {x: d => d.T / 2, y: "cell", text: d => `${d.T}`, fill: "white", fontWeight: "bold", fontSize: 13}
      ),
      Plot.ruleX([0])
    ]
  }));
}
```

```js
display(Inputs.table(strata.map(c => ({
  "In-degree": c.indeg,
  "Size": c.size,
  "n": c.n,
  "T preferred": c.T,
  "B preferred": c.B,
  "Tie": c.tie,
  "T%": c.t_pct + "%",
})), {layout: "auto", width}));
```

Treatment wins in every cell. The strongest effect is **dense × large** (10/10 T
preferred, 0 B) — exactly the regime where dependency context is richest and the
signature is most complex. **Non-dense × small** is the weakest (8/10), consistent
with the hypothesis that context matters less when the declaration is simple and
isolated.

## 3. Edit Distance to Target

Token-level Levenshtein distance between the original signature F and each
formalization candidate. Smaller = closer to the ground truth.

```js
display(Plot.plot({
  title: "Edit distance to target signature, by condition",
  subtitle: `B mean ${s.edit_mean_B} tokens · T mean ${s.edit_mean_T} tokens`,
  width,
  height: 320,
  marginLeft: 130,
  grid: true,
  color: {
    domain: ["B (baseline)", "T (treatment)"],
    range:  ["#dc2626", "#2563eb"],
    legend: true
  },
  x: {label: "Token-level Levenshtein distance to F"},
  y: {label: null},
  marks: [
    Plot.boxX(editScatter, {x: "edit_dist", y: "condition", fill: "condition", fillOpacity: 0.4}),
    Plot.ruleX([0])
  ]
}));
```

```js
display(Plot.plot({
  title: "Edit distance scatter: B vs T, by judge preference",
  subtitle: "Each point = one candidate. Colour = judge verdict.",
  width,
  height: 320,
  grid: true,
  color: {
    domain: ["T", "tie", "B"],
    range:  ["#2563eb", "#94a3b8", "#dc2626"],
    legend: true,
    label: "Judge"
  },
  x: {label: "Edit dist — Baseline (B)"},
  y: {label: "Edit dist — Treatment (T)"},
  marks: [
    Plot.line([{x:0,y:0},{x:110,y:110}], {stroke: "#ccc", strokeDasharray: "4,4"}),
    Plot.dot(
      cands,
      {x: "edit_dist_B", y: "edit_dist_T", stroke: "prefer", fill: "prefer",
       fillOpacity: 0.6, r: 5, tip: true,
       channels: {Name: "short_name", "In-deg": "indeg", "Size": "size"}}
    )
  ]
}));
```

Nearly all points fall **below the diagonal** — treatment signatures are closer to the
target. Points above the diagonal (T worse) are rare and concentrated in the
non-dense × small cell where the graph context is thinnest.

## 4. Dependency Context Size

How much context did the treatment condition actually receive?

```js
display(Plot.plot({
  title: "Predecessor count (dep_count) by stratum",
  subtitle: "Number of direct dependency nodes included in the treatment prompt (pre-truncation)",
  width,
  height: 280,
  marginLeft: 90,
  grid: true,
  x: {label: "dep_count", domain: [0, 220]},
  y: {label: null},
  color: {
    domain: ["dense", "medium", "non_dense"],
    range: ["#7c3aed", "#2563eb", "#0891b2"],
    legend: true
  },
  marks: [
    Plot.boxX(cands, {x: "dep_count", y: "indeg", fill: "indeg", fillOpacity: 0.5}),
    Plot.ruleX([0])
  ]
}));
```

Dense declarations have far more predecessors, giving the treatment condition a richer
context. Truncation (8 000-token cap) was **not triggered for any candidate** —
all dependency contexts fit within the budget.

## 5. Per-Candidate Table

```js
const selectedIndeg = view(Inputs.checkbox(
  ["dense", "medium", "non_dense"],
  {label: "In-degree stratum", value: ["dense", "medium", "non_dense"]}
));
const selectedSize = view(Inputs.checkbox(
  ["large", "small"],
  {label: "Size stratum", value: ["large", "small"]}
));
const selectedPrefer = view(Inputs.checkbox(
  ["T", "tie", "B"],
  {label: "Judge preference", value: ["T", "tie", "B"]}
));
```

```js
{
  const filtered = cands.filter(c =>
    selectedIndeg.includes(c.indeg) &&
    selectedSize.includes(c.size) &&
    selectedPrefer.includes(c.prefer)
  );
  display(Inputs.table(filtered.map(c => ({
    "Name": c.short_name,
    "In-deg": c.indeg,
    "Size": c.size,
    "Deps": c.dep_count,
    "Prefer": c.prefer,
    "Edit B": c.edit_dist_B,
    "Edit T": c.edit_dist_T,
    "Vac B": c.vacuous_B ? "yes" : "—",
    "Vac T": c.vacuous_T ? "yes" : "—",
    "Judge notes": c.judge_notes,
  })), {
    layout: "auto",
    width,
    rows: 15,
    sort: "Edit B",
    reverse: true,
  }));
  display(html`<div style="font-size:12px;color:#64748b;margin-top:6px">${filtered.length} of ${cands.length} candidates shown</div>`);
}
```

## 6. Design & Validity

```js
display(html`<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:16px 20px;font-size:13px;line-height:1.7">
<strong>Models</strong><br>
Informalizer: ${s.models.informalizer}<br>
Formalizer (B and T — identical): ${s.models.formalizer}<br>
Judge: ${s.models.judge}<br><br>
<strong>Strata cutoffs</strong> (computed on 329 981 eligible Mathlib nodes)<br>
In-degree: p25 = ${s.strata_cutoffs.p25_indeg}, p75 = ${s.strata_cutoffs.p75_indeg}
&nbsp;·&nbsp; Signature length: p25 = ${s.strata_cutoffs.p25_siglen} chars, p75 = ${s.strata_cutoffs.p75_siglen} chars<br><br>
<strong>Sample</strong>: 10 per (in-degree × size) cell × 6 cells = 60 candidates, seed ${s.seed}. No shortfalls.<br>
<strong>Validation</strong>: all 6 checks passed (no leakage, judge blinding confirmed, same formalizer for B and T).
</div>`);
```

### What we did NOT control for

- **Single judge, single model family** — Sonnet 4.5 judges outputs from Haiku 4.5, but both
  have internalized Mathlib. A "better" output might be recognized from training.
- **Dependency names leak area** — T's context reveals the mathematical domain, even without
  giving F's signature directly. This is partially intentional (it's the information the
  context is supposed to provide) but conflates "knowing the topic" with "having the right
  API".
- **No type-checking** — syntactically invalid Lean counts the same as valid under the judge.
- **n = 60** — underpowered for subtle per-cell effects; dense × large vs. non-dense × small
  is directionally interesting but not conclusive.
- **Opus unavailable on this Bedrock account** — judge is Sonnet, not a clearly stronger
  separate model family.
