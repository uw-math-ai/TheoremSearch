# Autoformalization Smoke-Test Candidates

**Purpose.** Three blueprint statements selected to drive the first
"graph context helps the prover" comparison run. Each one is:
1. **Genuinely unformalized** in the relevant Lean project at its current
   commit (verified by grep, not by trusting `informal_metadata.lean`).
2. **Surrounded by formalized siblings** in the informal dependency graph —
   so the "with graph context" arm has real Lean lemmas to inject.
3. **Concrete and well-typed** — a prover can succeed or fail unambiguously.

This file is paired with the broader candidate dataset described in
[`formalization_candidates.md`](./formalization_candidates.md) and the
per-anchor neighborhood walk documented there.

## Selection methodology

1. Start from the 500 anchors in
   `experiments/nl_fl_matching/data/top_formalization_candidates.csv` —
   the top rank-1 i→f matches from the blueprint gold pool (every anchor
   is a blueprint statement that has at least one `\lean{}` partner).
2. Walk each anchor's k=1 informal-dependency neighborhood (in + out edges
   from `informal_dependency`) and classify every neighbor's formalization
   status. See `experiments/nl_fl_matching/analysis/walk_neighborhoods.py`.
3. Filter to anchors with **≥5 resolved k=1 siblings AND ≥1 unformalized
   k=1 neighbor** (status ∈ `none`, `annotated_only`) — that's 110 of 500.
4. For each shortlisted neighbor, **grep the project repo's `*.lean` files**
   to eliminate false negatives (statements that are formalized but where
   the blueprint just omits the `\lean{}` annotation). See
   the `feedback_grep_before_formalize` memory note and the false-positive
   example below.

**False positive caught.** Initial slate included pfr's `rho-init`
("$\rho(U_A) = 0$"). Grep found it formalized as `rho_of_uniform` in
`PFR/RhoFunctional.lean:663`; the blueprint encoded the link as
`\label{rho-init}\label{rho_of_uniform}\leanok` instead of
`\lean{rho_of_uniform}`. Eliminated.

## The slate (3 candidates)

| id | repo | label / sid | type | k=1 ctx | grep-verified |
|---|---|---|---|---:|---|
| **A** | `RemyDegenne/brownian-motion` | `lem:IsLocalMartingale.martingale_iff_classDL` (`b8f7c652`) | `lemma` | 16 resolved | ✅ not in `BrownianMotion/**/*.lean`; blueprint marks `\notready` with empty proof |
| **B** | `RemyDegenne/brownian-motion` | `lem:IsLocalSubmartingale.submartingale_iff_classDL_of_nonnegative` (`5cfea075`) | `lemma` | 16 resolved | ✅ same as A; companion statement |
| **F** | `teorth/pfr` | `eta-def` (`3be0d32c`) | `definition` | 8 resolved | ✅ never bound to a `def` in `PFR/**/*.lean` — pfr hardcodes `p.η = 1/9` as a hypothesis instead. Useful as a trivial control. |

**Candidate attributes** (from RDS table `candidate_attributes`):

| | math_category | dist_undirected | dist_prereq→cons (ν_A) | dist_cite→dep | nearest_kind | true_inference |
|---|---|---:|---:|---:|---|---|
| A | `math.PR` | 1 | **1** | NULL | `resolved_annotation` | ✅ |
| B | `math.PR` | 1 | **1** | NULL | `resolved_annotation` | ✅ |
| F | `math.CO, math.PR` | 1 | NULL | **1** | `resolved_annotation` | ✅ |

All three are at undirected distance 1 (as designed). But notice the
directed-distance asymmetry:
- **A and B** are "consequence candidates": formalized prerequisites
  exist one hop UP (ν_A = 1), but no formalized consequence cites them.
  The prover's job is to compose formalized building blocks.
- **F (`eta := 1/9`)** is a "prerequisite candidate": no formalized
  prerequisite exists (F is a leaf definition with no `\uses`), but
  formalized consequences DO cite it (the pfr proofs assume `p.η = 1/9`).
  The prover's job is to introduce the definition that downstream Lean
  code already expects.

This is a useful distinction for the harness: A and B benefit most from
a premise pack of upstream-formalized lemmas; F benefits from showing
the prover what downstream consumers expect of the symbol.

See [`formalization_candidates.md` §Candidate attributes table](./formalization_candidates.md#candidate-attributes-table)
for the full schema, BFS source-set composition, and distribution
across the 326-candidate pool.

### A — `IsLocalMartingale.martingale_iff_classDL`

> A local martingale is a cadlag martingale if and only if it is of class DL.

- Blueprint source: `brownian-motion/blueprint/src/chapters/local_martingales.tex:902`
- Resolved k=1 deps (graph context the prover would see):
  - `IsLocalMartingale` — `BrownianMotion/StochasticIntegral/LocalMartingale.lean:24`
  - `ClassDL` (structure) — `BrownianMotion/StochasticIntegral/ClassD.lean:115`
  - `IsCadlag` (structure) — `BrownianMotion/StochasticIntegral/Cadlag.lean:28`
  - `Martingale` — Mathlib `Mathlib.Probability.Martingale.Basic`
  - Plus 12 more siblings in the same anchor neighborhood (e.g.
    `ClassDL.classD`, `Submartingale.classDL`, `Martingale.classDL`).

### B — `IsLocalSubmartingale.submartingale_iff_classDL_of_nonnegative`

> A nonnegative local submartingale is a cadlag submartingale if and only
> if it is of class DL.

- Blueprint source: `brownian-motion/blueprint/src/chapters/local_martingales.tex:913`
- Resolved k=1 deps largely overlap with A — the comparison can run both
  in the same harness session.

### F — `eta-def` (control)

> $\eta := 1/9$.

- Blueprint source: `pfr/blueprint/src/chapter/entropy_pfr.tex:3`
- Resolved k=1 deps include `entropic_PFR_conjecture`,
  `tau_strictly_decreases`, etc. — all of which use `p.η = 1/9` as a
  hypothesis but never define `η` itself.
- **Why a control:** a `def eta : ℝ := 1/9` is trivial syntactically.
  Both arms should succeed; if either fails, the harness has a bug. If
  both succeed, that's a baseline floor.

## Data accessibility

| artifact | location | size | committed |
|---|---|---:|---|
| Selection script | `experiments/nl_fl_matching/analysis/walk_neighborhoods.py` | — | ✅ |
| Per-anchor aggregate | `experiments/nl_fl_matching/data/neighborhoods.csv` | 166 KB | ✅ |
| Per-neighbor detail | `experiments/nl_fl_matching/data/neighborhoods_detail.jsonl` | 9.6 MB | ❌ (gitignored, regenerate via script) |
| Per-neighbor detail (queryable) | RDS table `formalization_candidate_neighborhood`, db `v2` | 14,084 rows | — |
| RDS table DDL | `experiments/nl_fl_matching/schema_neighborhoods.sql` | — | ✅ |

### Reproduce

```bash
RDS_HOST=theorem-search.cluster-cx0ei6kq0qcn.us-west-2.rds.amazonaws.com \
    python3 -m experiments.nl_fl_matching.analysis.walk_neighborhoods
```

Runtime: ~6s end-to-end (the table is idempotent; re-running upserts).

### Query examples

```sql
-- Anchors with the richest graph context AND at least one unformalized k=1 hole.
SELECT anchor_statement_id,
       COUNT(*) FILTER (WHERE k = 1 AND status = 'resolved')             AS k1_resolved,
       COUNT(*) FILTER (WHERE k = 1 AND status IN ('none','annotated_only')) AS k1_unformalized,
       COUNT(*) FILTER (WHERE k = 2 AND status = 'resolved')             AS k2_resolved
  FROM formalization_candidate_neighborhood
 WHERE pool_descriptor = 'gold_subset_i2f'
 GROUP BY anchor_statement_id
HAVING COUNT(*) FILTER (WHERE k = 1 AND status = 'resolved') >= 5
   AND COUNT(*) FILTER (WHERE k = 1 AND status IN ('none','annotated_only')) >= 1
 ORDER BY k1_resolved DESC
 LIMIT 20;

-- Pull the smoke-test candidates directly.
SELECT n.neighbor_statement_id, n.status,
       s.body AS neighbor_body, im.ref, im.label
  FROM formalization_candidate_neighborhood n
  JOIN statement s ON s.statement_id = n.neighbor_statement_id
  LEFT JOIN informal_metadata im ON im.statement_id = n.neighbor_statement_id
 WHERE n.neighbor_statement_id IN (
    'b8f7c652-...'::uuid,  -- A
    '5cfea075-...'::uuid,  -- B
    '3be0d32c-...'::uuid   -- F
 );
```

## Caveats for the harness

1. **Status `matched_only` count is 0** under the current pool. The pilot
   sweep was restricted to gold-pool queries, so neighbors (which are
   non-gold) never had a chance to be queried. Expanding the pilot to a
   broader pool would populate this bucket and likely surface more
   unformalized-but-semantically-known neighbors.
2. **k=2 contains thousands of candidates** (1,470 with status='none' across
   all anchors). The k=2 view is the right pool to mine for cycle 2 when
   we want larger anchor neighborhoods or are willing to accept a longer
   semantic gap between anchor and target.
3. **`annotated_only` is interesting too.** These are blueprint statements
   whose `\lean{}` annotation points at a decl that doesn't resolve —
   either upstream-migration to Mathlib (out of scope), refactor rename
   (fixable), or aspirational (genuine target). Worth a separate pass.

## What's next

| step | doc |
|---|---|
| Design the prover comparison harness (Aristotle, proof-only) | [`harness_design.md`](./harness_design.md) ✅ |
| Hand-write Lean signatures for A, B, F | ✅ — files under `experiments/nl_fl_matching/harness/{A,B,F}*/{no_graph,with_graph}.lean` |
| Cycle 2: expand anchor pool beyond blueprint gold (arXiv anchors with formalized neighbors) | see [bidirectional_matching.md](./bidirectional_matching.md) §"What we did NOT run" |
