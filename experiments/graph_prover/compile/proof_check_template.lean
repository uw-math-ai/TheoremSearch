import Mathlib
set_option autoImplicit false
set_option relaxedAutoImplicit false
set_option maxHeartbeats 1000000

{DECLARATION}

#print axioms cand

open Lean Elab Command in
run_cmd do
  let env ← getEnv
  match env.find? `cand with
  | some ci =>
      match ci.value? with
      | some v => logInfo s!"USED_CONSTANTS: {v.getUsedConstants.toList}"
      | none   => logInfo "USED_CONSTANTS: []"
  | none => logInfo "USED_CONSTANTS_MISSING"
