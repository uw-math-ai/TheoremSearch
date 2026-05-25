# Candidate A — `IsLocalMartingale.martingale_iff_classDL`

**Blueprint:** `brownian-motion/blueprint/src/chapters/local_martingales.tex:902`

> A local martingale is a cadlag martingale if and only if it is of class DL.

Status: `\notready`, empty proof in the blueprint. No matching decl in
`/tmp/simku22/repos/brownian-motion/BrownianMotion/**/*.lean` (grep-verified).

## Files

| file | purpose |
|---|---|
| `no_graph.lean` | Project imports + target with `sorry`. No premise hints. |
| `with_graph.lean` | Same imports + same target. Adds a 35-line `Premises` section with `example := @decl` references to the resolved-sibling decls predicted by the informal dep graph. |

## How to run

These files import `BrownianMotion.*`, so they must be compiled *inside*
a checkout of `RemyDegenne/brownian-motion` at tag `v4.29.0`. Two
options:

1. Copy each `.lean` into `brownian-motion/BrownianMotion/StochasticIntegral/`
   (or wherever), then submit to Aristotle via CLI / MCP.
2. Pass `--lean-path /path/to/brownian-motion` (or however the Aristotle
   CLI accepts external project context) so the imports resolve.

Run both arms with the same Aristotle budget. Record per arm:
- compiles? (Lean accepts the returned file)
- sorry-free? (no `sorry` in target body)
- axiom-free? (`#print axioms IsLocalMartingale.martingale_iff_classDL`
  shows only standard axioms, no `sorryAx`)
- wall time / tokens (if exposed)

## Premise pack provenance

35 decl names, queried from the RDS table
`formalization_candidate_neighborhood` (db `v2`) — the union of resolved
k=1 siblings across the 3 anchors that have target A as a k=1
informal-dep neighbor.

To regenerate or extend the pack:

```sql
SELECT DISTINCT unnest(resolved_decls) AS decl
  FROM formalization_candidate_neighborhood
 WHERE anchor_statement_id IN (
    '148afe52-f769-46d6-8aa4-d008c269af17',
    '3d6042b2-f01f-4d1a-a96c-5dc8143867b9',
    'ff18ba56-79f3-431e-a254-05cb333fec65'
 )
   AND k = 1
   AND status = 'resolved'
   AND neighbor_statement_id <> 'b8f7c652-f29c-48cb-9b59-8c8652e3699f'::uuid
 ORDER BY decl;
```

## If the signature doesn't type-check

The `variable` block in both files takes the intersection of the
variable conventions from `LocalMartingale.lean` and `ClassD.lean`. If
Lean complains, the most likely fixes:
- Add `[Nonempty ι]` or `[ConditionallyCompleteLinearOrderBot ι]`
- Adjust the `hX : IsLocalMartingale X 𝓕 P` parameter — the blueprint
  intent might require additional hypotheses we missed.

Either fix should land in **both** `no_graph.lean` and `with_graph.lean`
to keep the comparison clean.
