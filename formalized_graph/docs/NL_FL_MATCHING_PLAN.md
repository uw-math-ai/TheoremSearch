# NL ↔ FL Matching Pipeline — Living Plan

**Purpose.** Build the canonical natural-language ↔ formal-language matched-pair artifact that gates Experiments #1 (cyclic consistency), #2 (slogan ordering), #5.2 (search reversal on v4.29), and #6 (graphs make provers better). This is the second arm of TheoremSearch — mapping the global natural-language graph of math papers to the global formal graph of Lean formalizations.

**Status.**

| Section | Status |
|---|---|
| Reframe & literature anchored | ✅ |
| Schema alignment with `rds/core/` | ✅ |
| v4.29 project → source mapping | 🟡 partial (gaps below) |
| Blueprint annotation density spot-check | ✅ done — Tier A premise validated for apap + chandra-furst-lipton; PersistentDecomp downgraded |
| ProofBridge encoder availability | ✅ checked — **not released** |
| Pipeline architecture | 🟡 draft |
| Evaluation harness + cost model | 🟡 draft |
| First implementation milestone (M1) | ⬜ not started |

**Iteration log.**
- 2026-05-09: initial draft.
- 2026-05-09: blueprint density spot-check landed (§7). PersistentDecomp downgraded A→B (no blueprint, just a paper draft). New risk surfaced: ~75% of spot-checked apap `\lean{}` names don't exist in apap's local Lean source — likely upstreamed to Mathlib, renamed, or aspirational. Phase 1 resolution must happen against the unified `corpus_v2.db`, not against the project tree alone.

---

## 1. Reframe (the central insight)

The original framing — "filter low-degree FL nodes, ask LLM to match" — undersells what already exists. The single biggest finding from the literature survey:

> **Patrick Massot's `leanblueprint` (plasTeX plugin) provides hand-curated NL↔FL alignment as a free byproduct of how blueprint-driven Lean projects are written.** The `\lean{decl_name}` macro names the Lean declaration that proves a LaTeX statement; `\uses{label1, label2}` declares the LaTeX-side dep graph; `\proves{label}` ties proofs to statements; `\leanok` marks the Lean side complete.

When a project uses a blueprint with these macros densely populated, we get near-100%-precision matches at zero cost. **The pipeline must exploit this first**, then use LLM-judged matching only for projects without blueprints (or to extend coverage where blueprint annotation is sparse).

This stratifies the v4.29 corpus into tiers with very different methodology costs and confidence floors. See §3.

## 2. Why this is the right wedge in the literature

What exists:
- **[ProofNet](https://arxiv.org/abs/2302.12433)** (2023): 371 hand-aligned NL↔Lean pairs from undergrad textbooks. Tiny but gold-standard.
- **[Magnushammer](https://arxiv.org/abs/2303.04488) / LeanHammer**: contrastive premise selection. **FL→FL only** — orthogonal to us.
- **[Herald](https://arxiv.org/abs/2410.10878)** (ICLR 2025): 580k NL-FL statement pairs by *informalizing* Mathlib4 with Lean-Jixia + LLM. **Synthetic NL** — they generate NL from FL.
- **[CombiBench](https://arxiv.org/abs/2505.03171)** (May 2025; Yael Dillies co-author): 100 hand-paired Lean↔NL combinatorial problems. Closest peer to YD's projects in our v4.29 set — possible overlap to mine for free training/eval pairs.
- **[LeanExplore](https://arxiv.org/abs/2506.11085)** (June 2025): retrieval search engine.
- **[ProofBridge](https://arxiv.org/abs/2510.15681)** (Oct 2025): joint NL↔Lean embedding trained contrastively on 38.9k pairs (NuminaMath-Lean-PF). +3.28× Recall@1 over MiniLM. Encoder weights **not released** — see §6.
- **[Lean Finder](https://arxiv.org/abs/2510.15940)** (ICLR 2026): 1.4M query-code pairs (244k informalized + 244k formal + 582k synthesized queries + 337k proof states). +30% Recall over GPT-4o.

What's missing in the literature: **organic NL ↔ FL alignment at scale**. Every prior corpus is either (a) synthetic NL, (b) hand-paired (≤500 pairs), or (c) one-direction retrieval. **Aligning real arXiv prose to real Lean declarations across non-Mathlib formalization projects is a gap.** That's the publishable wedge.

## 3. Project tier table (v4.29 corpus)

Tiers reflect **availability of high-confidence ground truth**, not project quality.

| Project | Source | Tier | Best matching strategy | Verified blueprint pairs |
|---|---|---|---|---|
| **apap** | Bloom-Sisask, [arXiv:2302.07211](https://arxiv.org/abs/2302.07211) (Kelley-Meka) | **A** | Parse blueprint `\lean{}`/`\uses{}` | **38 distinct `\lean{}` names** across 49 envs (75.5% density). See §7. |
| **chandra-furst-lipton** | CFL 1983 STOC + [Gasarch survey](https://www.cs.umd.edu/~gasarch/BLOGPAPERS/multiparty-vdw.pdf) | **A** | Parse blueprint | **14 distinct `\lean{}` names** across 31 envs (45% density, 17 commented `% \lean{}` placeholders for unfinished). |
| **forbidden-matrix** | Forbidden matrix theory literature | A-stub | Parse blueprint, but yield is tiny | **2 `\lean{}` names** across 4 envs — blueprint is mostly stubs. Useful only as supplemental gold. |
| **PersistentDecomp** | Botnan-Crawley-Boevey, [arXiv:1811.08946](https://arxiv.org/abs/1811.08946) ("Decomposition of Persistence Modules", 2020 Proc AMS) | **B** ⬇ | No blueprint — just a paper draft in `Paper/` with `\newtheorem` envs and **zero `\lean{}` annotations** anywhere | downgraded from A |
| **gibbs-measure** | Georgii (1988) *Gibbs Measures and Phase Transitions* — textbook | **B** | Need textbook ingestion (not arXiv); LLM match by chapter | Medium |
| **cam-combi** | Cambridge Part II/III courses (LeanCamCombi) | **B** | Course-note ingestion + LLM match | Medium-low |
| **add-combi** | No single source — additive-combi library | **C** | Mathlib-style cross-paper LLM match | Low — many lemmas have no NL home |
| **misc-yd** | Many topics (Kneser, Sylvester-Chvatal, Cauchy-Davenport, Birkhoff, Minkowski-Carathéodory, …) | **C** | LLM match across many sources | Low |
| **combinatorial-games** | Various (likely Conway, Siegel) | **C** | LLM match (textbooks) | Low-medium |

**Reporting rule:** every metric in §8 is reported per tier. Pooling across tiers tells you nothing.

**Open mapping gaps** (the "2-minute ordeal" the user flagged — actionable list):
- Confirm Bloom-Sisask arXiv ID for apap (✓ done: 2302.07211).
- Confirm PersistentDecomp source paper has DOI / arXiv (proposed: 1811.08946 — verify).
- Decide ingestion strategy for textbook-sourced projects (gibbs-measure, cam-combi).
- For Tier C projects, decide whether to attempt matching at all in v1, or mark them out of scope.

## 4. Schema alignment

The recently-finalized `rds/core/` schema fits this pipeline cleanly. **No new tables required for matching itself** — `statement_link` is the right shape.

Relevant existing tables (from `rds/core/`):

```
paper(paper_id, kind {lean_repo|paper|textbook|open_project}, source, title, ...)
statement(statement_id, paper_id, formality {formal|informal|semiformal}, kind, body, proof)
formal_metadata(statement_id, file_path, decl_name, module, signature, docstring, tactic_summary)
informal_metadata(statement_id, ordinal, ref, label, note, pre_context, post_context)
informal_dependency(src_id, location, cite_id, cite_key, dep_id, ...)
formal_dependency(src_id, dep_id, tactic_context)
statement_link(a_id, b_id, relation, confidence, source, note)  -- a_id < b_id, symmetric
```

**How matching slots in:**

A matched pair (formal Lean statement F, informal LaTeX statement I) becomes a row in `statement_link`:

```
statement_link.relation = 'fl_nl_match'
statement_link.a_id     = min(F.statement_id, I.statement_id)
statement_link.b_id     = max(F.statement_id, I.statement_id)
statement_link.source   = 'blueprint' | 'llm_judge' | 'llm_endorsed' | 'manual'
statement_link.confidence = [0,1]
statement_link.note     = judge rationale, blueprint label, etc.
```

Multi-source matches (e.g., a pair found by both blueprint and LLM-judge) get **multiple rows** with different `relation`/`source` combinations or a single canonical row with `source` chosen by priority. Decision in §10.

**One gap that is NOT yet addressed by the schema:**

> **Project ↔ source-paper(s) association.** A `lean_repo` paper (e.g. apap) needs to point at its source `paper` (arXiv:2302.07211) so Phase 0 of the pipeline can drive candidate generation per project. There's currently no `project_source` table or self-FK.

**Proposed minimal addition** (open for review):

```sql
CREATE TABLE paper_source (
    project_paper_id UUID NOT NULL REFERENCES paper(paper_id) ON DELETE CASCADE,
    source_paper_id  UUID NOT NULL REFERENCES paper(paper_id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('primary','secondary','course','textbook')),
    note TEXT,
    PRIMARY KEY (project_paper_id, source_paper_id, role)
);
```

Alternative: a sidecar YAML in `formalized_graph/projects.json` instead of DB. The DB table is cleaner for joining; the YAML is cheaper to iterate. **Recommendation: YAML for now (M1), promote to DB if it sticks (M5+).**

**FL kind filter.** Since `statement.kind` is constrained to lean-graph's 12-label enum (`thm/def/ind/ctor/quot/rec/inst/struct/class/opaque/axiom/other`), the degree filter (Phase 2) translates directly:

- **Match candidates:** `kind IN ('thm', 'def', 'struct', 'class', 'ind')` AND `formal_metadata.docstring IS NOT NULL`
- **Skip:** `kind IN ('ctor', 'rec', 'quot', 'inst', 'opaque', 'axiom', 'other')` — auto-generated, low semantic content, or rarely 1-1 to NL

## 5. Pipeline architecture (5 phases)

```
Phase 0  Project ↔ source mapping  (paper_source / YAML sidecar)
   ↓
Phase 1  Blueprint ingestion        (Tier A → statement_link rows, source='blueprint')
   ↓
Phase 2  Degree filter on FL side   (drop ctors/recs/insts/etc., require docstring)
   ↓
Phase 3  Candidate generation       (3 channels, top-k=5 deduped)
            ├─ project-paper prior  (NL candidates from project's source paper(s))
            ├─ dense embedding kNN  (signature+docstring vs statement body+title)
            └─ lexical name match   (camelCase Lean ↔ tokenized NL)
   ↓
Phase 4  LLM judge (two-phase, modeled on pipeline/parse_dependencies/judge.py)
            ├─ 4a generate: propose match w/ rationale + confidence
            └─ 4b verify:    independent verifier, batched (mirrors _VERIFY_BATCH_SIZE=10)
   ↓
Phase 5  Write to statement_link    (1-1 enforcement is a downstream view, not stored)
```

**Why this beats "just LLM-match":** Phase 1 alone may give us 50%+ of high-quality matches across the v4.29 corpus for free. Phase 4 then extends and validates. Phase 1 matches double as the held-out gold set for Phase 4 calibration — no human-labeling cost for Tier A.

## 6. Encoder strategy

**ProofBridge result:** both [PrithwishJana/ProofBridge](https://github.com/PrithwishJana/ProofBridge) and [shreyascasturi/proofbridge-nesy-2026](https://github.com/shreyascasturi/proofbridge-nesy-2026) ship code + dataset construction scripts but **no released encoder weights or HuggingFace checkpoint** as of May 2026. NuminaMath-Lean-PF construction is reproducible but requires running their pipeline locally.

**Decision: don't depend on ProofBridge weights.** Three viable fallbacks, in order of preference:

1. **BGE-M3** (or BGE-large-en-v1.5) — strong multilingual embedder, accepts up to 8192 tokens, ~3 GB. Open weights, runs locally on a single GPU. No math-specific training but strong on technical English. **Recommended baseline.**
2. **OpenAI text-embedding-3-large** — managed, $0.13/M tokens, strong on technical content. Cheap to run as second channel; ablation candidate.
3. **Reproduce ProofBridge encoder** by running their training scripts on NuminaMath-Lean-PF. ~1 GPU-week of training. **Skip in v1**; revisit only if BGE-M3 underperforms in §8 ablations.

This is also a good place to revisit if [Lean Finder](https://arxiv.org/abs/2510.15940) releases their dataset (1.4M query-code pairs) — could provide ready-made positive pairs for fine-tuning a math-aware encoder.

## 7. Blueprint annotation density spot-check ✅

Repos cloned shallowly into `data/formalization_projects/` and grep-counted (excluding commented-out `% \lean{}` placeholders).

| Project | theorem-like envs | `\lean{name}` | `\leanok` | `\uses{...}` | density (`\lean`/envs) | distinct decl names |
|---|---:|---:|---:|---:|---:|---:|
| **apap** | 49 | 37 | 65 | 50 | **75.5%** | **38** |
| **chandra-furst-lipton** | 31 | 14 | 17 | 35 | 45.2% | **14** |
| **forbidden-matrix** | 4 | 2 | 4 | 1 | 50% (n=4) | 2 |
| **PersistentDecomp** | 0 (`Paper/` dir, no blueprint) | 0 | — | — | — | 0 |

**Total verified blueprint-derived pairs available: ~54** (38 + 14 + 2). Plenty for an apap-only gold set with held-out validation, plus 16 extra for cross-project sanity checks.

**Verdict:** Tier A premise **validated for apap**, **weakly validated for chandra-furst-lipton** (45% density is OK but ~half the envs are blueprint stubs that haven't been formalized yet), **forbidden-matrix is a stub blueprint** (only 4 statements total — useful only as supplemental gold), **PersistentDecomp downgraded to Tier B** (no blueprint, just a paper draft in `Paper/` with zero `\lean{}` annotations anywhere in the repo).

**Example annotated statement (apap, ff.tex):**
```latex
\begin{theorem}\label{ap_in_ff}
\lean{ap_in_ff}
\leanok
If $A_1, A_2, S \subseteq \mathbb{F}_q^n$ are such that $A_1$ and $A_2$ both have density at least $\alpha$ then there is a subspace $V$ of codimension
\[\mathrm{codim}(V) \le 2^{27}\log(\alpha)^2\log(\epsilon\alpha)^2\epsilon^{-2}\]
\end{theorem}
```

**Critical caveat — name resolution.** Of 4 spot-checked apap `\lean{}` names, **only 1 of 4 (`ap_in_ff`) actually exists in apap's local Lean tree.** The other 3 (`balance_conv`, `balance_dconv`, `cLpNorm_cconv_le_cLpNorm_cdconv`) appear nowhere in the 49 `*.lean` files of `apap/APAP/`. This is consistent with three explanations, in likely order:

1. **Upstreamed to Mathlib** — apap is an active project; lemmas regularly migrate to Mathlib once mature. The name now lives at the Mathlib FQN.
2. **Renamed** — refactor since the blueprint annotation was last updated.
3. **Aspirational** — the blueprint was written first and the Lean side was never finished. `\leanok=65 > \lean=37` is partly explained by `\leanok` being applied to proofs as well as statements, but it also suggests some projects mark proofs done before populating `\lean{}`.

**Operational consequence.** Phase 1 must resolve `\lean{name}` against the unified `corpus_v2.db` (which has full Mathlib + add-combi + the rest of the v4.29 batch once ingested), **not** against the local project tree alone. Names that fail to resolve become `unresolved_blueprint_pointer` rows that feed back as candidates for Phase 4 LLM matching. The resolution failure rate is itself a useful metric (it estimates the upstream-migration rate of formalization projects).

`leanblueprint` ships a `checkdecls` command that does this same resolution; we can either invoke it as a subprocess or replicate its logic in our Phase 1 scraper. **Recommendation: replicate the logic** so we can capture unresolved pointers as first-class data rather than just CLI errors.

**Quick scope question:** the v4.29 corpus has 9 projects total but I've only checked the four most likely Tier A candidates. Should we also clone+grep the remaining five (`add-combi`, `cam-combi`, `combinatorial-games`, `gibbs-measure`, `misc-yd`) before finalizing the tier table? It's another 2-minute job. Listed as next-action #2 in §13.

## 8. Evaluation harness

**Gold set construction (zero-cost path):**
- Tier A blueprint matches *are* the gold set. Hold out 20% of `apap`'s blueprint matches; train/calibrate the LLM judge on the other 80%; evaluate Phase 4 against the held-out 20%.
- Cross-tier validation: hand-label 50 matches each on `add-combi` and `misc-yd` (~30 min/project for a domain-fluent reviewer).
- **Free additional pairs to mine:** check whether [CombiBench's 100 pairs](https://arxiv.org/abs/2505.03171) (YD co-author) intersect our corpus.

**Metrics, reported per tier:**
- **Precision@1** — top-confidence match correct
- **Recall on gold set** — % of gold pairs the pipeline recovers
- **Coverage** — % of degree-filtered FL nodes with a confident match (threshold τ = 0.7)
- **Calibration curve** — confidence vs accuracy; ECE (expected calibration error)

**Ablations (the publishable contributions):**
1. **Channel ablation:** project-prior alone vs +embedding vs +lexical vs all three
2. **Embedder ablation:** BGE-M3 vs OpenAI text-embedding-3-large vs (eventually) ProofBridge
3. **Judge model ablation:** Sonnet 4.6 vs Opus 4.7 vs DeepSeek-V3 (cost vs precision)
4. **Verifier necessity:** Phase 4a alone vs 4a+4b
5. **Degree-filter sensitivity:** kind-filter and in-degree threshold sweep — at what point does coverage collapse?
6. **Blueprint-bootstrap value:** same pipeline with vs without Phase 1 priming

The ablation grid is the actual paper. "We built a matcher" isn't novel; "here's what each retrieval/judge component contributes on real organic NL↔FL data, stratified by source-availability tier" is.

## 9. Cost model

Rough envelope for v4.29 (~50–100k FL nodes after kind+docstring filter; 9 source assets across Tiers A/B/C):

| Cost item | Calculation | $ |
|---|---|---|
| FL embedding (text-embedding-3-large) | 100k × ~1k tok × $0.13/M | ~$13 |
| NL embedding (same) | 5k × ~500 tok × $0.13/M | <$1 |
| Phase 4a judge (Sonnet 4.6) | 50k × top-5 × ~3k in + 200 out × ($3/$15)/M | ~$630 |
| Phase 4b verifier (batched 10) | 5k calls × ~10k tok | ~$150 |
| **Total per full v4.29 run** | | **~$800–1000** |

Cheap enough for many ablation runs. Mathlib (380k nodes) would 4–8× this — still affordable. Use the existing `pipeline/parse_dependencies/judge.py` cost-tracking pattern.

## 10. Phased delivery plan

| Milestone | Deliverable | Time | Unblocks |
|---|---|---|---|
| **M0** | Confirm blueprint-density results, finalize Phase 0/1 design | depends on subagent | M1 |
| **M1** | `paper_source` populated (YAML sidecar); blueprint URLs verified | 1 day | M2 |
| **M2** | Phase 0+1 (blueprint scraper) — produces seed `statement_link` rows for apap + forbidden-matrix + any other Tier A | 2–3 days | gold-set evaluation |
| **M3** | Phase 2+3 (degree filter + 3-channel candidate generation), runnable on apap end-to-end | 2–3 days | M4 |
| **M4** | Phase 4 LLM judge mirroring `judge.py`; held-out apap blueprint set as gold | 2 days | real metrics |
| **M5** | Run full pipeline on all 9 v4.29 projects; publish `statement_link` rows + per-tier metrics | 1–2 days | **Experiments #1, #2, #5.2, #6 unblocked** |
| **M6** | Ablation grid (channels × embedders × judges) | 1 week | paper draft |
| **M7** | Scale to Mathlib — match Mathlib nodes against arXiv corpus where docref edges already point to papers | 2–3 weeks | the big claim |

M5 is the load-bearing milestone — it produces the matched-pair artifact every other experiment depends on.

## 11. Open risks (priority order)

1. **`\lean{}` name drift.** ~75% of spot-checked apap blueprint annotations don't resolve to apap's local Lean tree (likely upstreamed to Mathlib or renamed). Phase 1 must resolve against the unified `corpus_v2.db`, not the project repo — and capture unresolved pointers as a first-class output for Phase 4 fallback. **Mitigation: replicate `leanblueprint checkdecls` logic in our Phase 1 scraper.** New as of 2026-05-09.
2. **Tier A yield is small (~54 verified pairs across 3 blueprinted projects).** Enough for gold set + held-out validation, not enough to be the whole dataset. Phase 4 LLM matching is still essential to reach corpus-scale coverage. **Implication: don't oversell "blueprints solve it" — they bootstrap precision and gold-set construction.**
3. **Project-source ambiguity for "library" projects** (add-combi, misc-yd, combinatorial-games). Many Lean lemmas have no organic NL counterpart. The pipeline must mark "no match" as a valid outcome — force-matching garbage will poison downstream experiments.
4. **Encoder mismatch.** Lean signatures and LaTeX statements look very different. Generic encoders (BGE-M3, OpenAI) may underperform. ProofBridge's encoder is the obvious answer but **isn't released** (verified May 2026 — both GitHub repos ship code + dataset construction scripts only) → BGE-M3 first, revisit.
5. **Surface vs deep equivalence.** Same theorem appears as contrapositive, dual finite-field/integer cases, combinatorial vs probabilistic, etc. Phase 4 verifier prompt must explicitly handle equivalence-up-to-restatement.
6. **Multi-FL → single-NL mappings.** apap proves both finite-field-case and integer-case Lean theorems for one NL Theorem. `statement_link` permits this (no UNIQUE on either side); downstream views must handle multiplicity.
7. **CombiBench overlap unchecked.** YD's CombiBench may contain pairs that are in our v4.29 corpus. Free additional pairs — needs cross-walk.

## 12. Open questions for the user

- **Q1:** Confirm `paper_source` YAML-sidecar approach for M1 vs adding a SQL table now. Cost of YAML is cheap iteration; cost of late SQL migration is small. **Default: YAML.**
- **Q2:** For Tier C (add-combi, misc-yd, combinatorial-games), do we attempt matching at all in v1, or mark them out of scope for the first paper and revisit later? Tier C is where the pipeline will look weakest in metrics. **Recommendation: attempt with a clear "no match" outcome supported, and report Tier C separately.**
- **Q3:** Textbook ingestion for gibbs-measure (Georgii) and cam-combi (Cambridge courses) — buy/scan PDFs and OCR? Skip and treat as Tier C? This is non-trivial scope.
- **Q4:** Which judge model do we standardize on for the headline numbers? Sonnet 4.6 is the cost-balanced default; Opus 4.7 if we need the precision floor for Tier C.
- **Q5:** Should the matched pairs feed back into the typed-edge ablation for Experiment #1? (i.e., once we have FL↔NL pairs, does proof-edge-vs-sig-edge context affect cyclic round-trip success?) This is the cross-experiment hook.

## 13. Next concrete actions (post-iteration)

In execution order, after the user signs off on this doc:

1. ~~Spot-check blueprint density~~ ✅ done (§7).
2. **Clone + grep the other 5 v4.29 projects** (add-combi, cam-combi, combinatorial-games, gibbs-measure, misc-yd) for `\lean{}` density to finalize the tier table. ~5 minutes.
3. **Verify the PersistentDecomp arXiv ID** (1811.08946 candidate) and produce final v4.29 → source-paper YAML/CSV.
4. **Decide M1/Q1** (YAML sidecar vs SQL `paper_source` table).
5. **Spike Phase 1**: write a ~100-line `parse_blueprint.py` against apap. For each `\begin{theorem|lemma|...}\label{X}\lean{Y}` block, emit a JSONL row with `latex_label`, `lean_name`, `latex_body`, surrounding `\uses{...}` and `\proves{...}`. Then resolve `lean_name` against `corpus_v2.db` (Mathlib + projects union) — count how many resolve. **No DB writes yet** — prove the premise with concrete resolution numbers before committing.
6. After M2 metrics, decide whether to proceed to M3 or revisit encoder choice.

---

## Appendix A — Schema diff at a glance

What's in `rds/core/` that the matching pipeline depends on:

```
paper(paper_id, kind, source, external_id, ...)        -- existing, unchanged
statement(statement_id, paper_id, formality, kind, body, proof)   -- existing, unchanged
formal_metadata(statement_id, decl_name, module, signature, docstring, ...)  -- existing
informal_metadata(statement_id, ordinal, ref, label, ...)         -- existing
statement_link(a_id, b_id, relation, confidence, source, note)    -- existing, this is THE matching table
```

What this plan proposes adding:

```
paper_source(project_paper_id, source_paper_id, role, note)       -- M1, optional (YAML alternative)
```

That's the entire schema delta.

## Appendix B — Reuse from `pipeline/parse_dependencies/`

Direct templates to copy:
- `judge.py` two-phase generate→verify with `_VERIFY_BATCH_SIZE = 10` and per-batch endorsement
- `_call_judge()` API wrapper with finish-reason logging and cost tracking
- `_parse_judge_json()` / `_parse_verify_json()` defensive parsing
- `models.py` model config + cost-per-1m tracking
- `paginate_query` / `build_query` / `upsert_rows` infra
- Sharding via `hashtext(paper_id::text) %% n_shards = shard` for SLURM array jobs

The matching pipeline is structurally a sibling of `connect_judge_dependencies` — same shape, different inputs.

## Appendix C — What this unlocks downstream

| Experiment | What it needs from this pipeline | Status after M5 |
|---|---|---|
| #1 Cyclic Consistency + typed-edge ablation | Verified 1-1 NL↔FL pairs to round-trip | unblocked |
| #2 Slogan generation order | Same pairs, used for FL-side / NL-side slogan comparison | unblocked |
| #5.2 Search reversal on v4.29 | Same pairs as evaluation set | unblocked |
| #6 Provers helped by graphs | Same pairs to compare "graph-via-NL" vs "graph-via-FL" context for the same target | unblocked |
| #3 Sphere-eversion case study | Same pipeline applied once sphere-eversion (v4.28) is parsed | independent unblock |

---

*Last updated: 2026-05-09. Edit this file directly as decisions land.*
