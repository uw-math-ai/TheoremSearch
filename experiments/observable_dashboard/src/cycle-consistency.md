---
title: "Cycle Consistency Pilot"
toc: true
---

# Cycle Consistency Pilot

```js
const d = FileAttachment("data/cycle_consistency.json").json();
```

```js
const s = d.summary;
const cands = d.candidates;
const strata = d.strata;
const conds = d.conditions;
const ablJ  = d.ablation_judge;
const mc    = d.mcnemar_cis;
const editScatter = d.edit_scatter;
const jvtc = d.judge_vs_tc;
```

## Setup

**The question**: does giving a model access to the formal graph's dependency
context improve autoformalization quality?

We measure this with a **cycle-consistency** test: take a real Lean 4 declaration
F from Mathlib, have a model describe it in English (NL), then have a formalizer
try to reconstruct Lean from NL alone. If the reconstruction F' matches the
original F, the model preserved the meaning. The formal graph lets us provide F's
dependencies — the declarations F actually uses — as context to the formalizer.

In a sentence: *can knowing what a theorem depends on help you write it back in Lean?*

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

### Concrete example: what each condition actually sends

The candidate below is `ack_inj_left` from `Mathlib.Computability.Ackermann` —
7 predecessors, short signature, non-dense stratum. Toggle conditions to see
exactly what the formalizer receives in each case.

```js
{
  // Predecessor graph for ack_inj_left
  const exDeps = [
    {type:"proof", name:"Function.Injective.eq_iff"},
    {type:"proof", name:"ack"},
    {type:"proof", name:"ack_injective_left"},
    {type:"sig",   name:"Eq"},
    {type:"sig",   name:"Iff"},
    {type:"sig",   name:"Nat"},
    {type:"sig",   name:"ack"},
  ];
  const typeColor = {proof:"#2563eb", sig:"#7c3aed"};
  const cx = 300, cy = 170, R = 130;
  const nodeData = exDeps.map((dep, i) => {
    const angle = (2 * Math.PI * i / exDeps.length) - Math.PI / 2;
    return {
      x: cx + R * Math.cos(angle),
      y: cy + R * Math.sin(angle),
      name: dep.name.split(".").pop(),
      fullName: dep.name,
      type: dep.type,
    };
  });
  const linkData = nodeData.map(n => ({x1: cx, y1: cy, x2: n.x, y2: n.y, type: n.type}));

  display(html`<div style="margin-bottom:4px">
    <span style="font-size:11px;color:${typeColor.proof};font-weight:600;margin-right:14px">● proof edge</span>
    <span style="font-size:11px;color:${typeColor.sig};font-weight:600">● sig edge</span>
  </div>`);

  display(Plot.plot({
    width: 600, height: 340, margin: 20,
    x: {domain:[0,600], axis:null},
    y: {domain:[0,340], axis:null, reverse:true},
    marks: [
      Plot.link(linkData, {
        x1:"x1", y1:"y1", x2:"x2", y2:"y2",
        stroke: r => typeColor[r.type] ?? "#94a3b8",
        strokeOpacity: 0.5, strokeWidth: 1.5,
      }),
      Plot.dot(nodeData, {
        x:"x", y:"y", r: 8,
        fill: r => typeColor[r.type] ?? "#94a3b8",
        fillOpacity: 0.85, tip: true,
        channels: {Name: "fullName", "Edge type": "type"},
      }),
      Plot.dot([{x:cx, y:cy}], {x:"x", y:"y", r:14, fill:"#0f172a", stroke:"white", strokeWidth:2}),
      Plot.text(nodeData, {
        x: r => r.x + (r.x > cx+5 ? 12 : r.x < cx-5 ? -12 : 0),
        y: r => r.y + (r.y > cy+5 ? 14 : r.y < cy-5 ? -12 : 0),
        text:"name", fontSize:10,
        textAnchor: r => r.x > cx+5 ? "start" : r.x < cx-5 ? "end" : "middle",
        fill: r => typeColor[r.type] ?? "#94a3b8",
        fontWeight: 500,
      }),
      Plot.text([{x:cx, y:cy+22}], {x:"x", y:"y", text:["ack_inj_left"], fontSize:11, fontWeight:700, fill:"#0f172a", textAnchor:"middle"}),
    ],
  }));

  display(html`<div style="font-size:12px;color:#64748b;margin-top:4px">
    Target node (black) is <code>ack_inj_left</code>. Outer nodes are its 7 predecessors —
    declarations the original Lean proof actually uses. Hover for full names.
  </div>`);
}
```

```js
// Static example data shared across the reactive blocks below
const exampleData = {
  nl: "The Ackermann function is injective in its first argument when the second argument is held fixed: for natural numbers m₁, m₂, and n, we have ack(m₁, n) = ack(m₂, n) if and only if m₁ = m₂.",
  deps: [
    {type:"proof", name:"Function.Injective.eq_iff",   sig:"Function.Injective.eq_iff {α β} {f : α → β} (hf : Function.Injective f) {a b} : f a = f b ↔ a = b"},
    {type:"proof", name:"ack",                          sig:"ack : ℕ → ℕ → ℕ"},
    {type:"proof", name:"ack_injective_left",           sig:"ack_injective_left (n : ℕ) : Function.Injective fun m => ack m n"},
    {type:"sig",   name:"Eq",                           sig:"Eq.{u_1} {α : Sort u_1} : α → α → Prop"},
    {type:"sig",   name:"Iff",                          sig:"Iff (a b : Prop) : Prop"},
    {type:"sig",   name:"Nat",                          sig:"Nat : Type"},
    {type:"sig",   name:"ack",                          sig:"ack : ℕ → ℕ → ℕ"},
  ],
  rand_deps: [
    {type:"random", name:"max_ack_right",               sig:"max_ack_right (m n₁ n₂ : ℕ) : ack m (max n₁ n₂) = max (ack m n₁) (ack m n₂)"},
    {type:"random", name:"one_lt_ack_succ_right",       sig:"one_lt_ack_succ_right (m n : ℕ) : 1 < ack m (n + 1)"},
    {type:"random", name:"ack_lt_ack_right",            sig:"ack_lt_ack_right (m : ℕ) : StrictMono (ack m)"},
    {type:"random", name:"ack_pos",                     sig:"ack_pos (m n : ℕ) : 0 < ack m n"},
    {type:"random", name:"ack_succ_succ",               sig:"ack_succ_succ (m n : ℕ) : ack (m + 1) (n + 1) = ack m (ack (m + 1) n)"},
    {type:"random", name:"Nat.Partrec.Code.primrec_pappAck", sig:"Nat.Partrec.Code.primrec_pappAck : Primrec Nat.Partrec.Code.pappAck"},
    {type:"random", name:"ack_succ_zero",               sig:"ack_succ_zero (m : ℕ) : ack (m + 1) 0 = ack m 1"},
  ],
  outputs: {
    "B — baseline":    "-- model output (type-checks ✓, but wrong theorem)\ndef ack : ℕ → ℕ → ℕ\n  | 0, n => n + 1\n  | m + 1, 0 => ack m 1\n  | m + 1, n + 1 => ack m (ack (m + 1) n)\n\ntheorem ack_injective_first_arg ...\n-- ✗ Redefined ack instead of stating injectivity",
    "T-names":         "-- model output (type-checks ✓)\ntheorem ack_injective_left_iff (m₁ m₂ n : ℕ) : ack m₁ n = ack m₂ n ↔ m₁ = m₂ := by sorry\n-- ✓ Correct statement, wrong name, sorry proof",
    "T-random":        "-- model output (type-checks ✓)\ntheorem ack_injective_left_iff (m₁ m₂ n : ℕ) : ack m₁ n = ack m₂ n ↔ m₁ = m₂ := by sorry\n-- ✓ Correct statement, wrong name, sorry proof",
    "T — treatment":   "-- model output (type-checks ✓, judge preferred)\ntheorem ack_injective_left_iff (m₁ m₂ n : ℕ) : ack m₁ n = ack m₂ n ↔ m₁ = m₂ :=\n  (ack_injective_left n).eq_iff\n-- ✓ Correct statement + uses ack_injective_left from dep context",
  },
  // Actual scores for ack_inj_left from the run
  scores: {
    "B — baseline":  {tc: true,  edit: 50, vsT: "T won",         judgeNote: "B redefined ack unnecessarily; T uses injective_left helper matching target semantics"},
    "T-names":       {tc: true,  edit: 9,  vsT: "T won",         judgeNote: "T provides a proof using ack_injective_left; T-names only has sorry"},
    "T-random":      {tc: true,  edit: 9,  vsT: "T won",         judgeNote: "T provides actual proof via ack_injective_left; T-random uses sorry placeholder"},
    "T — treatment": {tc: true,  edit: 9,  vsT: "—",             judgeNote: "Reference condition (compared against in all pairwise judgments)"},
  },
};
```

```js
// Top-level view() — this is what makes the radio reactive across blocks
const condPicker = view(Inputs.radio(
  ["B — baseline","T-names","T-random","T — treatment"],
  {value:"T — treatment", label:"Condition"}
));
```

```js
// Reactively re-renders whenever condPicker changes
{
  const condColors = {"B — baseline":"#dc2626","T-names":"#f59e0b","T-random":"#7c3aed","T — treatment":"#2563eb"};
  const col = condColors[condPicker] ?? "#0f172a";

  function buildCtx(cond) {
    const nlBlock = `-- NL (all conditions)\n${exampleData.nl}`;
    if (cond === "B — baseline") return nlBlock;
    if (cond === "T-names") {
      return `${nlBlock}\n\n-- dep names only (no signatures)\n\n${exampleData.deps.map(r => `-- ${r.type}\n${r.name}`).join("\n\n")}`;
    }
    if (cond === "T-random") {
      return `${nlBlock}\n\n-- same-module random (7 nodes)\n\n${exampleData.rand_deps.map(r => `-- random\n${r.name} : ${r.sig}`).join("\n\n")}`;
    }
    return `${nlBlock}\n\n-- actual predecessor signatures (from graph)\n\n${exampleData.deps.map(r => `-- ${r.type}\n${r.name} : ${r.sig}`).join("\n\n")}`;
  }

  const inputText  = buildCtx(condPicker);
  const outputText = exampleData.outputs[condPicker] ?? "";

  const allConds = ["B — baseline","T-names","T-random","T — treatment"];
  const scoreStrip = html`<div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:12px 0">
    ${allConds.map(c => {
      const sc = exampleData.scores[c];
      const cc = condColors[c];
      const selected = c === condPicker;
      return html`<div style="padding:10px 12px;border-radius:6px;
                  background:${selected ? "#f8fafc" : "transparent"};
                  border:${selected ? `2px solid ${cc}` : "1px solid #e2e8f0"};
                  opacity:${selected ? 1 : 0.6}">
        <div style="font-size:10px;font-weight:700;text-transform:uppercase;
                    letter-spacing:.05em;color:${cc};margin-bottom:6px">${c}</div>
        <div style="display:flex;gap:10px;font-size:11px;color:#334155">
          <span><strong style="color:${sc.tc ? "#16a34a" : "#dc2626"}">${sc.tc ? "✓" : "✗"}</strong> typecheck</span>
          <span><strong>${sc.edit}</strong> edit</span>
          <span style="color:${sc.vsT === "T won" ? "#7c3aed" : "#94a3b8"}">${sc.vsT === "T won" ? "T won vs this" : sc.vsT}</span>
        </div>
      </div>`;
    })}
  </div>`;

  display(html`<div style="display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px;margin:12px 0">
    <div style="min-width:0">
      <div style="font-size:11px;font-weight:600;color:${col};text-transform:uppercase;
                  letter-spacing:.05em;margin-bottom:6px">Input to formalizer</div>
      <pre style="background:#f8fafc;border:1px solid #e2e8f0;border-left:3px solid ${col};
                  border-radius:4px;padding:10px 12px;font-size:11px;line-height:1.6;
                  overflow:auto;max-height:280px;white-space:pre-wrap;word-break:break-word;
                  overflow-wrap:anywhere;margin:0">${inputText}</pre>
    </div>
    <div style="min-width:0">
      <div style="font-size:11px;font-weight:600;color:${col};text-transform:uppercase;
                  letter-spacing:.05em;margin-bottom:6px">Formalizer output</div>
      <pre style="background:#f8fafc;border:1px solid #e2e8f0;border-left:3px solid ${col};
                  border-radius:4px;padding:10px 12px;font-size:11px;line-height:1.6;
                  overflow:auto;max-height:280px;white-space:pre-wrap;word-break:break-word;
                  overflow-wrap:anywhere;margin:0">${outputText}</pre>
    </div>
  </div>
  ${scoreStrip}
  <div style="background:#f8fafc;border-left:3px solid ${col};padding:8px 12px;
              font-size:12px;color:#475569;line-height:1.5;margin-top:6px">
    <strong>Judge note for ${condPicker}:</strong> ${exampleData.scores[condPicker].judgeNote}
  </div>
  <div style="font-size:12px;color:#64748b;margin-top:8px">
    Target: <code>ack_inj_left {m₁ m₂ n : ℕ} : ack m₁ n = ack m₂ n ↔ m₁ = m₂</code>
    · <code>Mathlib.Computability.Ackermann</code> · 7 predecessors · non-dense × small stratum
    · all four conditions type-check on this candidate but only T produced a real proof
  </div>`);
}
```

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

The **marginal** typecheck rates for B and T-names are identical (both 33%), but the
paired picture is more interesting. T-names doesn't help *the same* candidates as B
— it lifts some and drops others, net zero:

```js
{
  const pp = cands.filter(r => r.tc_B &&  r.tc_Tnames).length;
  const pf = cands.filter(r => r.tc_B && !r.tc_Tnames).length;
  const fp = cands.filter(r => !r.tc_B &&  r.tc_Tnames).length;
  const ff = cands.filter(r => !r.tc_B && !r.tc_Tnames).length;
  const ciLo = mc.B_vs_Tnames.ci_lo;
  const ciHi = mc.B_vs_Tnames.ci_hi;
  display(html`<table style="border-collapse:collapse;font-size:13px;margin:12px 0">
    <thead><tr style="background:#f1f5f9">
      <th style="padding:8px 14px;border:1px solid #e2e8f0"></th>
      <th style="padding:8px 14px;border:1px solid #e2e8f0;color:#f59e0b">T-names passes</th>
      <th style="padding:8px 14px;border:1px solid #e2e8f0;color:#f59e0b">T-names fails</th>
      <th style="padding:8px 14px;border:1px solid #e2e8f0">Row total</th>
    </tr></thead>
    <tbody>
      <tr>
        <td style="padding:8px 14px;border:1px solid #e2e8f0;font-weight:600;color:#dc2626">B passes</td>
        <td style="padding:8px 14px;border:1px solid #e2e8f0;text-align:center;background:#f0fdf4;font-weight:700">${pp}</td>
        <td style="padding:8px 14px;border:1px solid #e2e8f0;text-align:center;background:#fef2f2">${pf}</td>
        <td style="padding:8px 14px;border:1px solid #e2e8f0;text-align:center">${pp + pf}</td>
      </tr>
      <tr>
        <td style="padding:8px 14px;border:1px solid #e2e8f0;font-weight:600;color:#dc2626">B fails</td>
        <td style="padding:8px 14px;border:1px solid #e2e8f0;text-align:center;background:#fef2f2">${fp}</td>
        <td style="padding:8px 14px;border:1px solid #e2e8f0;text-align:center;background:#f8fafc">${ff}</td>
        <td style="padding:8px 14px;border:1px solid #e2e8f0;text-align:center">${fp + ff}</td>
      </tr>
      <tr style="background:#f1f5f9">
        <td style="padding:8px 14px;border:1px solid #e2e8f0;font-weight:600">Col total</td>
        <td style="padding:8px 14px;border:1px solid #e2e8f0;text-align:center">${pp + fp}</td>
        <td style="padding:8px 14px;border:1px solid #e2e8f0;text-align:center">${pf + ff}</td>
        <td style="padding:8px 14px;border:1px solid #e2e8f0;text-align:center">60</td>
      </tr>
    </tbody>
  </table>
  <div style="font-size:12px;color:#64748b;margin-top:4px">
    Green = both pass (${pp} candidates). Red = one passes, one fails (${pf + fp} candidates).
    McNemar 95% CI on difference: [${ciLo}pp, ${ciHi}pp].
  </div>`);
}
```

Only **13/20** B-passes overlap with T-names passes. T-names shifts *which*
candidates typecheck — 7 that baseline would fail it passes, and 7 that baseline
would pass it fails. A plausible mechanism: dep names push the formalizer toward
specific declarations in the neighbourhood; when it guesses the wrong one the
output is worse than no hint at all.

What reliably moves the needle is type *signatures*: T-random (55%) shows that
any same-area signatures help, and the full predecessor graph (63%) adds another
8pp by providing signatures directly constraining F's own types.

```js
display(html`<table style="border-collapse:collapse;font-size:13px;margin:8px 0 4px">
  <thead><tr style="background:#f1f5f9">
    <th style="padding:7px 12px;border:1px solid #e2e8f0;text-align:left">Comparison</th>
    <th style="padding:7px 12px;border:1px solid #e2e8f0;text-align:right">Δ (pp)</th>
    <th style="padding:7px 12px;border:1px solid #e2e8f0;text-align:right">95% CI</th>
    <th style="padding:7px 12px;border:1px solid #e2e8f0;text-align:left">Interpretation</th>
  </tr></thead>
  <tbody>
    ${[
      {cmp:"B vs T",        ci: mc.B_vs_T,        note:"Strong, robust signal"},
      {cmp:"T-names vs T",  ci: mc.Tnames_vs_T,   note:"Signatures matter a lot"},
      {cmp:"T vs T-random", ci: mc.T_vs_Trandom,  note:"CI crosses zero — directional only"},
      {cmp:"B vs T-names",  ci: mc.B_vs_Tnames,   note:"Names add nothing on average"},
    ].map(({cmp, ci, note}) => html`<tr>
      <td style="padding:7px 12px;border:1px solid #e2e8f0">${cmp}</td>
      <td style="padding:7px 12px;border:1px solid #e2e8f0;text-align:right;font-weight:600">${ci.delta > 0 ? "+" : ""}${ci.delta}pp</td>
      <td style="padding:7px 12px;border:1px solid #e2e8f0;text-align:right;font-family:monospace;font-size:11px">[${ci.ci_lo > 0 ? "+" : ""}${ci.ci_lo}, +${ci.ci_hi}]</td>
      <td style="padding:7px 12px;border:1px solid #e2e8f0;color:#475569">${note}</td>
    </tr>`)}
  </tbody>
</table>
<div style="font-size:11px;color:#94a3b8">McNemar exact binomial CI, n=60.</div>`);
```

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
  · Wilcoxon signed-rank W = ${s.wilcoxon_stat}, z = ${s.wilcoxon_z}, p < 1e-9
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
        {x:r=>r.T/2, y:"cell", text:r=>`${r.T}`,
         fill:"white", fontWeight:"bold", fontSize:13}),
      Plot.ruleX([0]),
    ]
  }));
}
```

Treatment wins in every cell. The strongest cell is **dense × large: 10/10/0**
(T/tie/B) — the regime where F is both widely cited and has a complex signature,
meaning its dep context is richest and there is the most structure to get right.

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
          text: r=>String(r.n), fontWeight:"bold", fontSize:12, fill:"white"})),
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
        x: r => r.jx + r.jitter_x,
        y: r => r.jy + r.jitter_y,
        stroke: r => verdictColor[r.judge_T_vs_Trandom] ?? "#94a3b8",
        fill:   r => verdictColor[r.judge_T_vs_Trandom] ?? "#94a3b8",
        fillOpacity: 0.7,
        r: 5,
        tip: true,
        channels: {Name: "short_name", "In-degree stratum": "indeg", "Size": "size"},
      }),
    ]
  }));
}
```

If the scatter is dense to read quickly, here's the same data as a 2×2 count table — judge verdict (rows) × whether T was the one that type-checked (columns):

```js
{
  const cells = [
    {judge:"Judge: T wins",        tc:"TC: only T passes", n: jvtc.filter(r=>r.judge_T_vs_Trandom==="T"      && r.tc_advantage_T===1).length},
    {judge:"Judge: T wins",        tc:"TC: same outcome",  n: jvtc.filter(r=>r.judge_T_vs_Trandom==="T"      && r.tc_advantage_T===0).length},
    {judge:"Judge: T wins",        tc:"TC: only T-random", n: jvtc.filter(r=>r.judge_T_vs_Trandom==="T"      && r.tc_advantage_T===-1).length},
    {judge:"Tie",                  tc:"TC: only T passes", n: jvtc.filter(r=>r.judge_T_vs_Trandom==="tie"    && r.tc_advantage_T===1).length},
    {judge:"Tie",                  tc:"TC: same outcome",  n: jvtc.filter(r=>r.judge_T_vs_Trandom==="tie"    && r.tc_advantage_T===0).length},
    {judge:"Tie",                  tc:"TC: only T-random", n: jvtc.filter(r=>r.judge_T_vs_Trandom==="tie"    && r.tc_advantage_T===-1).length},
    {judge:"Judge: T-random wins", tc:"TC: only T passes", n: jvtc.filter(r=>r.judge_T_vs_Trandom==="Trandom"&& r.tc_advantage_T===1).length},
    {judge:"Judge: T-random wins", tc:"TC: same outcome",  n: jvtc.filter(r=>r.judge_T_vs_Trandom==="Trandom"&& r.tc_advantage_T===0).length},
    {judge:"Judge: T-random wins", tc:"TC: only T-random", n: jvtc.filter(r=>r.judge_T_vs_Trandom==="Trandom"&& r.tc_advantage_T===-1).length},
  ];
  const judgeRows = ["Judge: T wins","Tie","Judge: T-random wins"];
  const tcCols    = ["TC: only T passes","TC: same outcome","TC: only T-random"];

  display(html`<table style="border-collapse:collapse;font-size:13px;margin:10px 0">
    <thead><tr style="background:#f1f5f9">
      <th style="padding:8px 12px;border:1px solid #e2e8f0"></th>
      ${tcCols.map(c => html`<th style="padding:8px 12px;border:1px solid #e2e8f0;text-align:center">${c}</th>`)}
    </tr></thead>
    <tbody>
      ${judgeRows.map(jr => html`<tr>
        <td style="padding:8px 12px;border:1px solid #e2e8f0;font-weight:600">${jr}</td>
        ${tcCols.map(tc => {
          const cell = cells.find(c => c.judge===jr && c.tc===tc);
          const n = cell ? cell.n : 0;
          const highlight = jr==="Judge: T-random wins" && tc==="TC: only T passes";
          return html`<td style="padding:8px 12px;border:1px solid #e2e8f0;text-align:center;
            font-weight:${n>0?"600":"400"};
            background:${highlight?"#f5f3ff":n>0?"#f8fafc":"#fff"};
            color:${highlight?"#7c3aed":"inherit"}">${n}</td>`;
        })}
      </tr>`)}
    </tbody>
  </table>
  <div style="font-size:12px;color:#64748b">Shaded cell = judge preferred T-random but T was the one that type-checked.</div>`);
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

## 7. Generalization: Does the Effect Hold Outside Mathlib?

Pilot and ablation are both Mathlib-only. To test whether the B vs T effect
generalizes, we ran the same pilot (60 candidates, B + T + judge) on
`combinatorial-games` — a Lean 4 project of 2,435 eligible declarations
downstream of Mathlib.

Setup was identical: same models, same prompts, same judge protocol, same
seed. Candidates were sampled uniformly (no stratification — the project is
too skewed across in-degree × signature-size cells to fill the 3×2 grid).

```js
display(html`<table style="border-collapse:collapse;font-size:13px;margin:14px 0">
  <thead><tr style="background:#f1f5f9">
    <th style="padding:8px 14px;border:1px solid #e2e8f0;text-align:left">Project</th>
    <th style="padding:8px 14px;border:1px solid #e2e8f0;text-align:right">n</th>
    <th style="padding:8px 14px;border:1px solid #e2e8f0;text-align:right">T preferred</th>
    <th style="padding:8px 14px;border:1px solid #e2e8f0;text-align:right">B preferred</th>
    <th style="padding:8px 14px;border:1px solid #e2e8f0;text-align:right">Tie</th>
    <th style="padding:8px 14px;border:1px solid #e2e8f0;text-align:right">Wilcoxon p</th>
    <th style="padding:8px 14px;border:1px solid #e2e8f0;text-align:right">Edit B → T</th>
  </tr></thead>
  <tbody>
    <tr>
      <td style="padding:8px 14px;border:1px solid #e2e8f0">Mathlib (pilot)</td>
      <td style="padding:8px 14px;border:1px solid #e2e8f0;text-align:right">60</td>
      <td style="padding:8px 14px;border:1px solid #e2e8f0;text-align:right;color:#2563eb;font-weight:700">49 (82%)</td>
      <td style="padding:8px 14px;border:1px solid #e2e8f0;text-align:right;color:#dc2626">3 (5%)</td>
      <td style="padding:8px 14px;border:1px solid #e2e8f0;text-align:right;color:#6b7280">8 (13%)</td>
      <td style="padding:8px 14px;border:1px solid #e2e8f0;text-align:right;font-family:monospace;font-size:11px">1.8e-10</td>
      <td style="padding:8px 14px;border:1px solid #e2e8f0;text-align:right">31.7 → 14.5</td>
    </tr>
    <tr>
      <td style="padding:8px 14px;border:1px solid #e2e8f0">combinatorial-games</td>
      <td style="padding:8px 14px;border:1px solid #e2e8f0;text-align:right">60</td>
      <td style="padding:8px 14px;border:1px solid #e2e8f0;text-align:right;color:#2563eb;font-weight:700">46 (77%)</td>
      <td style="padding:8px 14px;border:1px solid #e2e8f0;text-align:right;color:#dc2626">5 (8%)</td>
      <td style="padding:8px 14px;border:1px solid #e2e8f0;text-align:right;color:#6b7280">9 (15%)</td>
      <td style="padding:8px 14px;border:1px solid #e2e8f0;text-align:right;font-family:monospace;font-size:11px">9.4e-9</td>
      <td style="padding:8px 14px;border:1px solid #e2e8f0;text-align:right">13.3 → 8.1</td>
    </tr>
  </tbody>
</table>
<div style="font-size:12px;color:#64748b;margin-top:4px">
  Same models, same prompts, same judge protocol. combinatorial-games signatures are
  shorter on average → smaller absolute edit distances, but the proportional T advantage
  holds (B is ~1.6× the edit distance of T in both projects).
</div>`);
```

The B vs T effect replicates: T preferred at very similar rates (82% vs. 77%),
with significance well below 1e-8 in both. The edit-distance gap is proportionally
similar despite different absolute magnitudes. **This is not Mathlib-specific.**

### Ablation on combinatorial-games

We also ran the T-names and T-random ablations on the same 60 candidates
(reusing the NLs, swapping only the formalizer's context). Comparing
ablation-judge counts side-by-side:

```js
display(html`<table style="border-collapse:collapse;font-size:13px;margin:12px 0">
  <thead><tr style="background:#f1f5f9">
    <th style="padding:8px 12px;border:1px solid #e2e8f0;text-align:left">Comparison</th>
    <th style="padding:8px 12px;border:1px solid #e2e8f0;text-align:right">Mathlib</th>
    <th style="padding:8px 12px;border:1px solid #e2e8f0;text-align:right">combinatorial-games</th>
    <th style="padding:8px 12px;border:1px solid #e2e8f0;text-align:left">Verdict</th>
  </tr></thead>
  <tbody>
    <tr>
      <td style="padding:8px 12px;border:1px solid #e2e8f0">T vs T-names (T wins / tie / T-names wins)</td>
      <td style="padding:8px 12px;border:1px solid #e2e8f0;text-align:right;font-family:monospace">33 / 16 / 11</td>
      <td style="padding:8px 12px;border:1px solid #e2e8f0;text-align:right;font-family:monospace;color:#16a34a;font-weight:700">33 / 14 / 13</td>
      <td style="padding:8px 12px;border:1px solid #e2e8f0;color:#16a34a">Replicates exactly — signatures are load-bearing in both projects</td>
    </tr>
    <tr>
      <td style="padding:8px 12px;border:1px solid #e2e8f0">T vs T-random (T wins / tie / T-random wins)</td>
      <td style="padding:8px 12px;border:1px solid #e2e8f0;text-align:right;font-family:monospace">27 / 11 / 22</td>
      <td style="padding:8px 12px;border:1px solid #e2e8f0;text-align:right;font-family:monospace;color:#dc2626">20 / 18 / 22</td>
      <td style="padding:8px 12px;border:1px solid #e2e8f0;color:#dc2626">Does <em>not</em> replicate — T-random edges T here (within Mathlib pilot CI [−8.3, +25.0]pp)</td>
    </tr>
  </tbody>
</table>`);
```

**This sharpens the story.** The structural finding — that knowing *type signatures*
of relevant declarations is essential, while knowing just their *names* adds nothing —
is robust across both projects, with identical T-wins counts (33/60). The further
claim that *actual predecessor* signatures beat *random same-module* signatures
was already marginal at n=60 (CI [−8.3, +25.0]pp in Mathlib) and doesn't replicate
on combinatorial-games. The formal graph buys you *signatures*, but choosing
predecessor signatures over arbitrary same-module signatures is not a reliable win.

What was *not* tested here:
- **Typecheck signal**: skipped for non-Mathlib because each project pins its own
  Lean dependencies. To run typecheck against combinatorial-games, we'd need
  `import CombinatorialGames` plus its own lakefile.
- **Stratified breakdown**: combinatorial-games' eligible pool is heavily
  small-signature, so the dense×large cell can't be populated.

A natural next step is to run the same test across 4–5 more downstream projects
(PersistentDecomp, cam-combi, etc.) for a tighter generalization claim, and to
set up per-project typecheck environments so the second metric becomes available.

---

## 8. Limitations

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
  dep overlap, 17/60 candidates >50%). This is a confound for any claim about topical
  vs. structural signal.

- **NL name leakage.** The informalizer was not told to avoid mentioning F's name.
  Post-hoc: 10/60 NLs contain F's last name component verbatim; 9/60 contain a
  CamelCase part. Sensitivity check on the clean-NL subset (46/60):
  B = 32.6%, T = 63.0% — identical to the
  full sample (33% / 63%), so the finding is robust but gap magnitudes are
  conservative-biased toward zero when the name is present in both prompts.

- **Dep context truncation in dense-large stratum.** The 8 000-token cap (≈32 000
  chars) truncated deps for 2/10 dense-large candidates (up to 29 deps dropped).
  For those candidates, T's context is the first ~150 deps by edge-type + name
  order, not all deps. The \`dep_truncated\` column records exact counts.

- **F_T uses F's exact name 21/60 times vs F_B 8/60.** The judge sees the correct
  declaration name in T's output more often, which may inflate judge preference for
  T independent of semantic quality. This is one more reason to treat typecheck rate
  as the primary metric.
