# Candidate F — `eta := 1/9` (control)

**Blueprint:** `pfr/blueprint/src/chapter/entropy_pfr.tex:3`

> $\eta := 1/9$.

A literal one-line constant. **Trivial sanity control** — both arms
should succeed instantly. If either fails, the harness has a bug.

## Why F is shape-different from A/B

A and B are "consequence candidates": formalized prerequisites exist
upstream, the prover must compose them.

F is a "prerequisite candidate": no formalized prerequisite exists
(η has no `\uses{…}` deps), but **formalized consumers** exist
downstream (`entropic_PFR_conjecture`, `tau_strictly_decreases`, etc.
all take `(hpη : p.η = 1/9)` as a hypothesis).

The premise pack therefore surfaces *downstream consumers* rather
than upstream lemmas — see `with_graph.lean` Premises section.

The current pfr code carries η as a hypothesis-bound numeric on a
`tauMinimizer` package, not as a free-standing `def`. The blueprint
explicitly defines it as a top-level symbol. Aristotle should produce
either form; we'll accept whichever it returns as long as it
type-checks.

## Files

| file | purpose |
|---|---|
| `no_graph.lean` | Imports + namespace + `def eta : ℝ := 1/9`. |
| `with_graph.lean` | Same + 7-decl premise pack (downstream consumers). |

## Run

```bash
python3 -m experiments.nl_fl_matching.harness.orchestrator \
    --candidates F_eta_def --arms no_graph,with_graph \
    --project-dir /tmp/simku22/repos/pfr
```

Note: `--project-dir` is **pfr**, not brownian-motion. The orchestrator
stages F's `.lean` files into `pfr/PFR/_Harness/` by default.

## Per-candidate attribute snapshot

| attribute | value |
|---|---|
| `math_category` | `math.CO`, `math.PR` |
| `distance_undirected` | 1 |
| `distance_prereq_to_cons` (ν_A) | NULL (no formalized prereq above) |
| `distance_cite_to_dep` | 1 (formalized consumers cite it) |
| `nearest_interface_kind` | `resolved_annotation` |
| `true_inference` | True |
