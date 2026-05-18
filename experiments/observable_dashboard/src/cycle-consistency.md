---
title: "Cycle Consistency Pilot"
toc: true
---

# Cycle Consistency Pilot

```js
const d = FileAttachment("data/cycle_consistency.json").json();
const s = d.summary;
const cands = d.candidates;
const strata = d.strata;
const conds = d.conditions;
const ablJ  = d.ablation_judge;
const editScatter = d.edit_scatter;
const jvtc = d.judge_vs_tc;
```

## Setup

**The question**: does giving a model the formal graph's dependency context improve
cycle consistency for autoformalization?

**Cycle consistency** is the round-trip F → NL → F'. We take a real Lean 4
declaration F from Mathlib, generate an informal English description NL (using
the model's own words, no graph), then ask a formalizer to reconstruct a Lean
declaration from NL alone. A system is cycle-consistent if the reconstruction
matches the original.

### The four conditions

We ran the formalizer (Claude Haiku 4.5 via Bedrock, same model for all) on the
same 60 NLs under four conditions that vary only what context is appended:

```js
display(html`<table style="width:100%;border-collapse:collapse;font-size:13px;margin:12px 0">
  <thead><tr style="background:#f1f5f9">
    <th style="padding:8px 12px;text-align:left;border:1px solid #e2e8f0">ID</th>
    <th style="padding:8px 12px;text-align:left;border:1px solid #e2e8f0">Name</th>
    <th style="padding:8px 12px;text-align:left;border:1px solid #e2e8f0">What the formalizer receives</th>
    <th style="padding:8px 12px;text-align:left;border:1px solid #e2e8f0">Why it exists</th>
  </tr></thead>
  <tbody>
    ${[
      {id:"B", color:"#dc2626", name:"Baseline", input:"NL only", why:"No graph context — pure re-formalization from prose"},
      {id:"T-names", color:"#f59e0b", name:"Names-only", input:"NL + predecessor full_names (no type signatures)", why:"Tests whether knowing the names of F's deps (domain hint) is enough"},
      {id:"T-random", color:"#7c3aed", name:"Random same-module", input:"NL + signatures of dep_count(F) random nodes from the same Lean module", why:"Tests whether any same-area signatures help, vs. specifically the predecessor relationship"},
      {id:"T", color:"#2563eb", name:"Treatment", input:"NL + full_name : signature for each actual predecessor of F in the formal graph", why:"Ground-truth dep context — what the graph uniquely provides"},
    ].map(r => html`<tr>
      <td style="padding:8px 12px;border:1px solid #e2e8f0;font-weight:700;color:${r.color}">${r.id}</td>
      <td style="padding:8px 12px;border:1px solid #e2e8f0">${r.name}</td>
      <td style="padding:8px 12px;border:1px solid #e2e8f0;font-family:monospace;font-size:12px">${r.input}</td>
      <td style="padding:8px 12px;border:1px solid #e2e8f0;color:#475569">${r.why}</td>
    </tr>`)}
  </tbody>
</table>`);
```

**Predecessors** of F are the nodes F directly depends on — the declarations whose
names and types appear in F's signature or proof. They are the 1-hop outgoing
neighbors of F in the formal graph (`source_id = F`, across all edge types:
`proof`, `sig`, `def`, `field`, `extends`, `docref`).

### How we scored each output

**Type-check** (primary): each output is wrapped in `import Mathlib` and run
through `lake env lean` against Mathlib v4.29.0. Pass = elaborates without errors
(sorry is allowed; it suppresses proof obligations but not type errors). This is
model-free ground truth.

**Judge** (secondary): Claude Sonnet 4.5 is shown the target signature F and two
candidate outputs with randomised A/B labels. It answers: which candidate more
accurately matches the target semantically? The judge sees no condition labels and
has no knowledge of which output came from which condition. Blinding map stored
separately from results.

**Edit distance**: token-level Levenshtein between F's original signature and each
output. Descriptive only.

### Sample

60 Mathlib theorems and definitions (seed 42), stratified by in-degree (how widely
cited: dense/medium/non-dense) × signature length (large/small). 10 per cell.
All four conditions share the same 60 NLs — only the formalizer input varies.

---

## 1. Core Finding: Signatures Are the Load-Bearing Component

The type-check rate across all four conditions is the cleanest summary.

```js
{
  display(html`<div style="display:flex;gap:16px;flex-wrap:wrap;margin:18px 0 8px">
    ${conds.map(c => html`
      <div style="flex:1;min-width:170px;padding:16px 20px;border-radius:10px;
                  background:#f8fafc;border:2px solid ${c.color};text-align:center">
        <div style="font-size:11px;font-weight:600;text-transform:uppercase;
                    letter-spacing:.05em;color:${c.color};margin-bottom:4px">${c.id}</div>
        <div style="font-size:12px;color:#64748b;margin-bottom:10px">${c.desc}</div>
        <div style="font-size:38px;font-weight:700;color:${c.color}">${c.tc_pass}<span style="font-size:18px;font-weight:400;color:#94a3b8">/60</span></div>
        <div style="font-size:11px;color:#64748b;margin-top:2px">type-check pass</div>
        <div style="margin-top:10px;height:6px;border-radius:3px;background:#e2e8f0">
          <div style="height:6px;border-radius:3px;background:${c.color};width:${c.tc_pct}%"></div>
        </div>
        <div style="font-size:20px;font-weight:600;margin-top:4px">${c.tc_pct}%</div>
      </div>`)}
  </div>
  <div style="font-size:12px;color:#64748b;margin-top:4px">
    n = 60 per condition · same NLs across all conditions · Mathlib v4.29.0
  </div>`);
}
```

**B and T-names are identical (both 33%).** Knowing the names of F's predecessors —
which reveals the mathematical domain and namespace — adds exactly nothing over
having no context at all. What moves the needle is having actual type *signatures*:
T-random (55%) shows that any same-area signatures help, and the full predecessor
graph (63%) adds another 8pp by providing signatures directly relevant to F's own
types.

At n=60, pairwise 95% CIs on typecheck-rate differences are roughly ±13–16pp.
The B = T-names result (0pp gap) is the most robust; the T vs T-random gap (8pp)
is directional.

---

## 2. Pilot: Baseline vs. Treatment

Before running the ablation we ran the core B vs T comparison on all 60 candidates.
The judge (Sonnet 4.5) was shown the original signature and the two outputs — B and
T — with A/B labels randomised per item. It chose which matched the target better.

```js
display(html`<div style="display:flex;gap:24px;flex-wrap:wrap;margin:14px 0">
  ${[
    {label:"T preferred", val: s.t_count,   pct: s.t_pct,   color:"#2563eb"},
    {label:"B preferred", val: s.b_count,   pct: s.b_pct,   color:"#dc2626"},
    {label:"Tie",         val: s.tie_count, pct: s.tie_pct, color:"#6b7280"},
  ].map(({label,val,pct,color}) => html`
    <div style="flex:1;min-width:150px;padding:16px 20px;border-radius:10px;
                background:#f8fafc;border:1px solid #e2e8f0;text-align:center">
      <div style="font-size:40px;font-weight:700;color:${color}">${val}</div>
      <div style="font-size:13px;color:#64748b;margin-top:2px">${label}</div>
      <div style="font-size:20px;font-weight:600;margin-top:4px">${pct}%</div>
    </div>`)}
</div>
<div style="font-size:12px;color:#475569;margin-top:4px">
  Judge: Sonnet 4.5 · prompt: "which candidate more accurately matches the target signature semantically?"
  · Wilcoxon signed-rank W = ${s.wilcoxon_stat}, p ≈ ${s.wilcoxon_p?.toExponential(1) ?? "—"}
  · ${s.t_prefers_and_tc} of ${s.t_count} judge-preferred T outputs also type-check
</div>`);
```

The judge strongly prefers treatment outputs (82% of cases). The Wilcoxon test on
the paired +1/−1/0 coding is significant (p ≈ 0), but n=60 is underpowered for
subtle effects — read this as a strong directional signal.

Stratified by in-degree × signature size:

```js
{
  const indegOrder = ["dense","medium","non_dense"];
  const sizeOrder  = ["large","small"];
  const allCells   = indegOrder.flatMap(i => sizeOrder.map(s => ({
    indeg:i, size:s, cell:`${i} × ${s}`
  })));
  display(Plot.plot({
    title: "Judge preference by stratum — B vs T",
    subtitle: "dense = top-25% in-degree (widely cited); large = top-25% signature length",
    marginLeft: 130, marginRight: 60, width, height: 260,
    x: {label:"Candidates", grid:true},
    y: {label:null, domain: allCells.map(c=>c.cell)},
    color: {
      domain:["T (treatment)","tie","B (baseline)"],
      range: ["#2563eb","#94a3b8","#dc2626"],
      legend: true,
    },
    marks: [
      Plot.barX(
        strata.flatMap(c=>[
          {cell:c.cell, val:c.T,   cond:"T (treatment)"},
          {cell:c.cell, val:c.tie, cond:"tie"},
          {cell:c.cell, val:c.B,   cond:"B (baseline)"},
        ]),
        Plot.stackX({x:"val",y:"cell",fill:"cond",
          order:["T (treatment)","tie","B (baseline)"],tip:true})
      ),
      Plot.text(strata.filter(c=>c.T>0),
        {x:d=>d.T/2, y:"cell", text:d=>`${d.T}`,
         fill:"white", fontWeight:"bold", fontSize:13}),
      Plot.ruleX([0]),
    ]
  }));
}
```

Treatment wins in every cell. The effect is largest for dense × large declarations —
exactly where the dep context is richest (most predecessors, most complex signature).

---

## 3. Ablation: What Is Actually Doing the Work?

### Why we ran it

The B vs T result is strong, but the treatment context does two things at once:
it gives the model the right **type signatures** (structural) *and* reveals the
**mathematical domain** via the predecessor names (topical). We can't tell from
B vs T alone which of these is load-bearing.

Three new conditions let us pull them apart:

- **B vs T-names**: if T-names ≈ B, domain hints alone don't help — signatures are
  what matters.
- **T-random vs B**: if T-random > B, any same-area signatures help, not just
  predecessor signatures specifically.
- **T vs T-random**: if T > T-random, the actual predecessor relationship adds
  signal beyond "same neighbourhood."

### What the judge saw

For each of the 60 candidates the judge was shown the original signature F and
two outputs with randomised A/B labels — in one run T vs T-names, in another T vs
T-random. Same prompt as the pilot: "which candidate more accurately matches the
target signature semantically?" B vs T-names and B vs T-random were not judged
directly; those comparisons come from the typecheck rates (which are model-free
and don't require transitivity).

```js
{
  const bars = [
    {pair:"T vs T-names",  cond:"T",        n: ablJ.T_vs_Tnames.T,       color:"#2563eb"},
    {pair:"T vs T-names",  cond:"tie",      n: ablJ.T_vs_Tnames.tie,     color:"#94a3b8"},
    {pair:"T vs T-names",  cond:"T-names",  n: ablJ.T_vs_Tnames.Tnames,  color:"#f59e0b"},
    {pair:"T vs T-random", cond:"T",        n: ablJ.T_vs_Trandom.T,       color:"#2563eb"},
    {pair:"T vs T-random", cond:"tie",      n: ablJ.T_vs_Trandom.tie,     color:"#94a3b8"},
    {pair:"T vs T-random", cond:"T-random", n: ablJ.T_vs_Trandom.Trandom, color:"#7c3aed"},
  ];
  display(Plot.plot({
    title: "Ablation judge preference — T compared against each new condition",
    subtitle: "Each row = 60 paired judgments. Judge sees target signature + two outputs, A/B randomised.",
    width,
    height: 160,
    marginLeft: 130,
    x: {label: "Candidates", grid: true, domain:[0,60]},
    y: {label: null},
    color: {
      domain: ["T","tie","T-names","T-random"],
      range:  ["#2563eb","#94a3b8","#f59e0b","#7c3aed"],
      legend: true,
    },
    marks: [
      Plot.barX(bars,
        Plot.stackX({x:"n", y:"pair", fill:"cond",
          order:["T","tie","T-names","T-random"]})),
      Plot.text(bars.filter(b=>b.n>3),
        Plot.stackX({x:"n", y:"pair", z:"cond",
          order:["T","tie","T-names","T-random"],
          text: d=>String(d.n), fontWeight:"bold", fontSize:12, fill:"white"})),
      Plot.ruleX([0]),
    ]
  }));
}
```

### What it tells us

The judge and the type-checker agree directionally but not in magnitude:

```js
display(Inputs.table([
  {Comparison: "B vs T-names",  "TC rate B": "33%", "TC rate other": "33%", "Gap": "0pp",  "Judge (T wins)": "—",  "Interpretation": "Names alone add nothing"},
  {Comparison: "T-random vs B", "TC rate B": "33%", "TC rate other": "55%", "Gap": "+22pp","Judge (T wins)": "—",  "Interpretation": "Any same-area signatures help"},
  {Comparison: "T vs T-random", "TC rate B": "55%", "TC rate other": "63%", "Gap": "+8pp", "Judge (T wins)": "45% vs 37%", "Interpretation": "Actual dep graph adds signal beyond neighbourhood"},
  {Comparison: "T vs T-names",  "TC rate B": "33%", "TC rate other": "63%", "Gap": "+30pp","Judge (T wins)": "55% vs 18%", "Interpretation": "Type signatures are essential"},
], {layout:"auto", width}));
```

The judge and typecheck diverge most on T vs T-random (judge: 45/37 nearly tied;
typecheck: 63% vs 55% with an 8pp gap). The next section shows why.

---

## 4. Why Judge and Type-Check Diverge on T-random

The judge evaluates whether an output **statement is semantically plausible** given
the NL. The type-checker asks whether it **elaborates** — are the names, argument
types, and return type actually well-typed in Lean?

A T-random output can look plausible — it uses the right vocabulary because same-module
declarations share types and namespaces — but fail to elaborate because the specific
argument structure is wrong. The judge rates it highly; the type-checker rejects it.
These are different failure modes, not one metric being "wrong."

The scatter below maps each of the 60 candidates on two axes: did the judge prefer
T or T-random? Did T type-check when T-random didn't (or vice versa)? The shaded
top-right region contains candidates where the judge preferred T-random but T was
the one that actually type-checked.

```js
{
  const verdictColor = {"T":"#2563eb","Trandom":"#7c3aed","tie":"#94a3b8"};
  let s2 = 42;
  const rng = () => { s2 ^= s2<<13; s2 ^= s2>>17; s2 ^= s2<<5; return (s2>>>0)/2**32; };

  const pts = jvtc.map(r => ({
    ...r,
    jx: {"T":-1,"tie":0,"Trandom":1}[r.judge_T_vs_Trandom] ?? 0,
    jy: r.tc_advantage_T,
    jitter_x: (rng()-0.5)*0.35,
    jitter_y: (rng()-0.5)*0.35,
  }));

  display(Plot.plot({
    title: "T vs T-random: judge preference vs. type-check outcome (per candidate)",
    width,
    height: 300,
    marginLeft: 110,
    marginBottom: 60,
    x: {
      domain: [-1.8, 1.8],
      tickFormat: v => v === -1 ? "Judge: T wins" : v === 0 ? "Tie" : "Judge: T-random wins",
      ticks: [-1, 0, 1],
      label: null,
    },
    y: {
      domain: [-1.8, 1.8],
      tickFormat: v => v === 1 ? "TC: only T passes" : v === 0 ? "TC: same outcome" : "TC: only T-random passes",
      ticks: [-1, 0, 1],
      label: null,
    },
    color: {
      domain: ["T", "tie", "Trandom"],
      range: ["#2563eb", "#94a3b8", "#7c3aed"],
      legend: true,
      label: "Judge verdict",
    },
    marks: [
      Plot.ruleX([0], {stroke: "#e2e8f0"}),
      Plot.ruleY([0], {stroke: "#e2e8f0"}),
      Plot.rect([{x1:0, x2:1.8, y1:0, y2:1.8}], {
        x1:"x1", x2:"x2", y1:"y1", y2:"y2",
        fill:"#7c3aed", fillOpacity:0.06,
      }),
      Plot.text([{x:0.9, y:1.55, text:"plausible statement,"}],
        {x:"x", y:"y", text:"text", fontSize:10, fill:"#7c3aed"}),
      Plot.text([{x:0.9, y:1.3, text:"wrong types"}],
        {x:"x", y:"y", text:"text", fontSize:10, fill:"#7c3aed", fontStyle:"italic"}),
      Plot.dot(pts, {
        x: d => d.jx + d.jitter_x,
        y: d => d.jy + d.jitter_y,
        stroke: d => verdictColor[d.judge_T_vs_Trandom] ?? "#94a3b8",
        fill:   d => verdictColor[d.judge_T_vs_Trandom] ?? "#94a3b8",
        fillOpacity: 0.7,
        r: 5,
        tip: true,
        channels: {Name: "short_name", "In-degree stratum": "indeg", "Size": "size"},
      }),
    ]
  }));
}
```

---

## 5. Edit Distance to Target Signature

Token-level Levenshtein between F's original signature and each output.
Smaller = closer to the ground truth structurally. This is a distance metric,
not a validity metric — an output can be close in edit distance but still wrong,
or far but semantically equivalent.

```js
display(Plot.plot({
  title: "Edit distance to F's original signature, by condition",
  subtitle: "T-names output is structurally far from the target even though it uses the right vocabulary.",
  width,
  height: 240,
  marginLeft: 130,
  grid: true,
  x: {label: "Token-level Levenshtein distance"},
  y: {label: null, domain: ["B (baseline)", "T-names", "T-random", "T (treatment)"]},
  color: {
    domain: ["B (baseline)","T-names","T-random","T (treatment)"],
    range:  ["#dc2626","#f59e0b","#7c3aed","#2563eb"],
  },
  marks: [
    Plot.boxX(editScatter, {x: "edit_dist", y: "condition", fill: "condition", fillOpacity: 0.5}),
    Plot.ruleX([0]),
  ]
}));
```

```js
display(Inputs.table(conds.map(c => ({
  "Condition": c.label,
  "Input": c.desc,
  "Type-checks": `${c.tc_pass}/60 (${c.tc_pct}%)`,
  "Edit mean": c.edit_mean,
  "Edit median": c.edit_median,
})), {layout:"auto", width}));
```

---

## 6. Per-Candidate Detail

```js
const selPrefer = view(Inputs.checkbox(
  ["T","tie","B"], {label:"B vs T verdict", value:["T","tie","B"]}
));
const selTC = view(Inputs.checkbox(
  ["T passes","T fails"], {label:"T type-check", value:["T passes","T fails"]}
));
```

```js
{
  const filtered = cands.filter(c =>
    selPrefer.includes(c.prefer) &&
    (c.tc_T ? selTC.includes("T passes") : selTC.includes("T fails"))
  );
  display(Inputs.table(filtered.map(c=>({
    "Declaration":   c.short_name,
    "In-degree":     c.indeg,
    "Sig size":      c.size,
    "Dep count":     c.dep_count,
    "B vs T":        c.prefer,
    "T vs T-names":  c.judge_T_vs_Tnames  || "—",
    "T vs T-random": c.judge_T_vs_Trandom || "—",
    "TC: B":         c.tc_B      ? "✓":"✗",
    "TC: T":         c.tc_T      ? "✓":"✗",
    "TC: T-names":   c.tc_Tnames ? "✓":"✗",
    "TC: T-random":  c.tc_Trandom? "✓":"✗",
    "Edit B":        c.edit_dist_B,
    "Edit T":        c.edit_dist_T,
    "Judge notes":   c.judge_notes,
  })), {layout:"auto", width, rows:12}));
  display(html`<div style="font-size:12px;color:#64748b;margin-top:4px">${filtered.length} of ${cands.length} shown</div>`);
}
```

---

## 7. Limitations

- **n = 60.** Pairwise 95% CIs on typecheck-rate differences are ~±13–16pp. The
  B = T-names result (0pp gap) is the most robust claim. The T vs T-random gap
  (8pp) is directional only.

- **T-random is a weak null.** Same-module nodes share vocabulary and types with F.
  On average 38% of a candidate's predecessor names share its top-level namespace
  prefix; 17/60 candidates have >50%. A stronger null would be random nodes from a
  different module entirely.

- **Typecheck and judge measure different things.** Typecheck = elaborability.
  Judge = semantic plausibility of the statement. Both matter; neither supersedes.

- **No Opus judge.** Sonnet 4.5 judges Haiku 4.5 outputs; both have Mathlib in
  their training data. B vs T-names and B vs T-random were not judged directly —
  LLM judge preferences are not reliably transitive.

- **Namespace leakage.** The verbatim-name check in validation passes, but
  predecessor names implicitly identify F's mathematical area (38% mean same-namespace
  dep overlap). This is a confound for any claim about topical vs. structural signal.
