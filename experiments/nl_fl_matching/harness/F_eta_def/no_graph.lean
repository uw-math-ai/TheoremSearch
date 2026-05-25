/-
Candidate F — no-graph arm.

Blueprint (pfr / blueprint/src/chapter/entropy_pfr.tex:3):
  $\eta := 1/9$.

A literal one-line constant definition. Sanity-control candidate:
both arms should succeed trivially; if either fails the harness has
a bug.

NOTE: pfr's existing code carries `η = 1/9` as a hypothesis on a
`p : tauMinimizer ...` package rather than as a top-level `def`. Our
target here is the blueprint's symbolic definition — a free-standing
`def eta : ℝ := 1/9`.
-/

import Mathlib.Tactic

namespace PFR

/-- η := 1/9 (PFR's parameter choice for the entropy iteration). -/
noncomputable def eta : ℝ := 1 / 9

end PFR
