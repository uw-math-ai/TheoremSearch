---
title: "Cycle Consistency Pilot"
toc: true
---

# Cycle Consistency Pilot

Does providing formal-graph dependency context improve **cycle consistency** for
autoformalization? We ran a paired experiment on 60 Mathlib declarations —
F → NL → F' — under four conditions that isolate *what* in the dep context drives
any improvement.

```js
const d = FileAttachment("data/cycle_consistency.json").json();
```

```js
const s = d.summary;
const cands = d.candidates;
const strata = d.strata;
const conds = d.conditions;
const ablJ  = d.ablation_judge;
const editScatter = d.edit_scatter;
const jvtc = d.judge_vs_tc;
```

## 1. The Core Finding: Signatures Do the Work

Four formalizer conditions on the same 60 NLs. Type-check rate against Mathlib
v4.29.0 is the primary validity signal — it is model-free, unlike the judge.

```js
{
  display(html`<div style="display:flex;gap:16px;flex-wrap:wrap;margin:18px 0 8px">
    ${conds.map(c => html`
      <div style="flex:1;min-width:170px;padding:16px 20px;border-radius:10px;
                  background:#f8fafc;border:2px solid ${c.color};text-align:center">
        <div style="font-size:11px;font-weight:600;text-transform:uppercase;
                    letter-spacing:.05em;color:${c.color};margin-bottom:6px">${c.label}</div>
        <div style="font-size:12px;color:#64748b;margin-bottom:10px">${c.desc}</div>
        <div style="font-size:38px;font-weight:700;color:${c.color}">${c.tc_pass}<span style="font-size:18px;font-weight:400;color:#94a3b8">/60</span></div>
        <div style="font-size:11px;color:#64748b;margin-top:2px">type-check pass</div>
        <div style="margin-top:10px;height:6px;border-radius:3px;background:#e2e8f0">
          <div style="height:6px;border-radius:3px;background:${c.color};width:${c.tc_pct}%"></div>
        </div>
        <div style="font-size:13px;font-weight:600;margin-top:4px">${c.tc_pct}%</div>
      </div>`)}
  </div>
  <div style="font-size:12px;color:#64748b;margin-top:4px">
    Type-checked against Mathlib v4.29.0 via batched <code>lake env lean</code> with namespace isolation.
    All four conditions use the same formalizer model (Haiku 4.5) on the same 60 NLs.
  </div>`);
}
```

**T-names (33%) ties baseline exactly (33%).** Knowing the names of F's
dependencies — which reveals the mathematical domain and namespace — adds nothing
to type-check validity. T-random (55%) shows that actual type *signatures* of
same-area declarations do help, even without the predecessor relationship. The full
dep graph (63%) adds another 8pp on top by providing signatures that are directly
relevant to F's own types.

At n=60 with binary outcomes, pairwise 95% confidence intervals on these differences
are roughly ±13–16pp, so the T vs T-random gap (8pp) and T vs B gap (30pp) should
be read as direction, not magnitude. The T-names = B result is the most robust: a
point estimate of zero with a symmetric CI means names alone are consistent with
adding nothing.

## 2. Pilot Result: B vs T

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
  Judge (Sonnet 4.5) · Wilcoxon W = ${s.wilcoxon_stat}, p ≈ ${s.wilcoxon_p?.toExponential(1) ?? "—"}
  · n = ${s.n} · ${s.t_prefers_and_tc} candidates both judge-preferred <em>and</em> type-check
</div>`);
```

## 3. Judge vs. Type-Check: Two Different Signals

The judge sees T and T-random as nearly tied (45% vs 37%). The type-check sees a
larger gap (63% vs 55%). These are measuring different things: the judge evaluates
whether the output *statement* is semantically plausible; the type-checker asks
whether it *elaborates*. A well-formed Lean statement with wrong argument types can
look plausible to the judge but fail elaboration — that's not the judge being
"fooled," it's the two metrics measuring different failure modes.

The scatter below shows where they agree and disagree on the T vs T-random
comparison. Top-right: judge preferred T-random, but T was the one that
type-checked. These are cases where T-random produced plausible vocabulary but
incorrect types.

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
    title: "T vs T-random: judge preference vs. type-check outcome",
    width,
    height: 280,
    marginLeft: 100,
    marginBottom: 60,
    x: {
      domain: [-1.8, 1.8],
      tickFormat: v => v === -1 ? "Judge: T wins" : v === 0 ? "Tie" : "Judge: T-random wins",
      ticks: [-1, 0, 1],
      label: null,
    },
    y: {
      domain: [-1.8, 1.8],
      tickFormat: v => v === 1 ? "TC: T only" : v === 0 ? "TC: same" : "TC: T-random only",
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
      Plot.text([{x:0.9, y:1.5, text:"plausible but wrong types"}],
        {x:"x", y:"y", text:"text", fontSize:10, fill:"#7c3aed", fontStyle:"italic"}),
      Plot.dot(pts, {
        x: d => d.jx + d.jitter_x,
        y: d => d.jy + d.jitter_y,
        stroke: d => verdictColor[d.judge_T_vs_Trandom] ?? "#94a3b8",
        fill:   d => verdictColor[d.judge_T_vs_Trandom] ?? "#94a3b8",
        fillOpacity: 0.7,
        r: 5,
        tip: true,
        channels: {Name: "short_name", "indeg": "indeg", "size": "size"},
      }),
    ]
  }));
}
```

## 4. Ablation Judge Preferences

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
    title: "Ablation: judge preferences (each paired against T)",
    subtitle: "Judge sees T vs one other condition; A/B labels randomised per item.",
    width,
    height: 160,
    marginLeft: 130,
    x: {label: "Candidates (n=60 per pair)", grid: true, domain:[0,60]},
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

The judge's view is broadly consistent with typecheck: T beats T-names clearly
(55%/18%), and T-random sits between them (45%/37%). Note that B vs T-names and
B vs T-random were not judged directly — LLM judge preferences are not reliably
transitive, so those comparisons should be read from the typecheck rates, not inferred.

## 5. Edit Distance — All Four Conditions

```js
display(Plot.plot({
  title: "Token-level Levenshtein distance to target signature",
  subtitle: "T-names edit distance stays near baseline despite better vocabulary — the types are wrong.",
  width,
  height: 240,
  marginLeft: 130,
  grid: true,
  x: {label: "Edit distance (tokens)"},
  y: {label: null, domain: ["B (baseline)", "T-names", "T-random", "T (treatment)"]},
  color: {
    domain: ["B (baseline)","T-names","T-random","T (treatment)"],
    range:  ["#dc2626","#f59e0b","#7c3aed","#2563eb"],
  },
  marks: [
    Plot.boxX(editScatter, {
      x: "edit_dist", y: "condition", fill: "condition", fillOpacity: 0.5,
    }),
    Plot.ruleX([0]),
  ]
}));
```

```js
display(Inputs.table(conds.map(c => ({
  "Condition": c.label,
  "Input": c.desc,
  "Type-checks": `${c.tc_pass}/60 (${c.tc_pct}%)`,
  "Edit dist (mean)": c.edit_mean,
  "Edit dist (median)": c.edit_median,
})), {layout:"auto", width}));
```

## 6. Stratified Preference (B vs T, pilot)

```js
{
  const indegOrder = ["dense","medium","non_dense"];
  const sizeOrder  = ["large","small"];
  const allCells   = indegOrder.flatMap(i => sizeOrder.map(s => ({
    indeg:i, size:s, cell:`${i} × ${s}`
  })));
  display(Plot.plot({
    title: "B vs T preference by stratum",
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

## 7. Per-Candidate Table

```js
const selPrefer = view(Inputs.checkbox(
  ["T","tie","B"], {label:"B vs T", value:["T","tie","B"]}
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
    "Name":          c.short_name,
    "Indeg":         c.indeg,
    "Size":          c.size,
    "Deps":          c.dep_count,
    "B vs T":        c.prefer,
    "T vs Tnames":   c.judge_T_vs_Tnames  || "—",
    "T vs Trandom":  c.judge_T_vs_Trandom || "—",
    "TC: B":         c.tc_B      ? "✓":"✗",
    "TC: T":         c.tc_T      ? "✓":"✗",
    "TC: Tnames":    c.tc_Tnames ? "✓":"✗",
    "TC: Trandom":   c.tc_Trandom? "✓":"✗",
    "Edit B":        c.edit_dist_B,
    "Edit T":        c.edit_dist_T,
  })), {layout:"auto", width, rows:15}));
  display(html`<div style="font-size:12px;color:#64748b;margin-top:4px">${filtered.length} of ${cands.length} shown</div>`);
}
```

## 8. Design & Limitations

```js
display(html`<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;
  padding:16px 20px;font-size:13px;line-height:1.7">
<strong>Conditions</strong><br>
<strong>B</strong> — NL only &nbsp;·&nbsp;
<strong>T-names</strong> — NL + predecessor <code>full_name</code> only (no type sigs) &nbsp;·&nbsp;
<strong>T-random</strong> — NL + <code>dep_count(F)</code> random same-module nodes, full sigs &nbsp;·&nbsp;
<strong>T</strong> — NL + actual predecessor <code>full_name : signature</code> blocks<br><br>
<strong>Models</strong> — Formalizer (all conditions): ${s.models.formalizer} · Judge: ${s.models.judge}<br>
<strong>Type-check</strong> — Batched <code>import Mathlib; lake env lean</code> against v4.29.0,
namespace-isolated per candidate. Assertion verified line mapping after each batch.<br>
<strong>Sample</strong> — 60 candidates, seed ${s.seed}, same NLs reused across all conditions
</div>`);
```

- **n = 60 is small.** 95% CIs on pairwise typecheck-rate differences are ~±13–16pp. The T-names = B result (0pp gap) is the most robust; the T vs T-random gap (8pp) is directional only.
- **T-random is a weak null.** Same-module nodes share vocabulary and types with F. On average 38% of a candidate's dep names share its top-level namespace prefix. A stronger null would be random nodes from a *different* module.
- **Typecheck and judge measure different things.** Typecheck measures elaborability; the judge measures semantic plausibility of the statement. Both are useful; neither supersedes the other. The top-right quadrant of §3 (plausible but wrong types) is the clearest example of the gap.
- **No Opus judge.** Sonnet 4.5 judges Haiku 4.5 outputs; both have internalized Mathlib. B vs T-names and B vs T-random were not judged directly — transitive inference from judge pairs is unreliable.
- **Namespace leakage not fully controlled.** The verbatim-name check in validation passes, but predecessor names implicitly identify F's mathematical area. 17/60 candidates have >50% same-namespace predecessors. This is a confound for T vs T-names.
