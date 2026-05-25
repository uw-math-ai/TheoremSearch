# Candidate B — `IsLocalSubmartingale.submartingale_iff_classDL_of_nonnegative`

**Blueprint:** `brownian-motion/blueprint/src/chapters/local_martingales.tex:913`

> A nonnegative local submartingale is a cadlag submartingale if and
> only if it is of class DL.

Status: `\notready`, empty proof in the blueprint. No matching decl in
`brownian-motion/BrownianMotion/**/*.lean` (grep-verified).

## Files

| file | purpose |
|---|---|
| `no_graph.lean` | Project imports + target with `sorry`. |
| `with_graph.lean` | Same + 35-decl premise pack (informal-dep graph prediction). |

Companion to candidate A (`IsLocalMartingale.martingale_iff_classDL`).
Same anchor neighborhoods (3 overlapping anchors); same 35-decl premise
pack. The two candidates differ only in: (a) target type uses
`IsLocalSubmartingale` instead of `IsLocalMartingale`, and (b) extra
hypothesis `hX_nonneg : ∀ t ω, 0 ≤ X t ω` matching the blueprint's
"nonnegative" qualifier.

Run with the same project-dir as A:
```bash
python3 -m experiments.nl_fl_matching.harness.orchestrator \
    --candidates B_submartingale_iff_classDL --arms no_graph,with_graph \
    --project-dir /tmp/simku22/repos/brownian-motion
```

## Per-candidate attribute snapshot (from `candidate_attributes`)

| attribute | value |
|---|---|
| `math_category` | `math.PR` |
| `distance_undirected` | 1 |
| `distance_prereq_to_cons` (ν_A) | 1 |
| `distance_cite_to_dep` | NULL (consequence candidate) |
| `nearest_interface_kind` | `resolved_annotation` |
| `true_inference` | True |
