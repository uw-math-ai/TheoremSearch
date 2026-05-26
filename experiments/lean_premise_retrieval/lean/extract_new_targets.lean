import Mathlib
import Lean
open Lean Lean.Elab.Command Lean.PrettyPrinter

/-- Build the large-corpus formalization target set. A target is a theorem that
is (a) defined in a `Mathlib.` module of v4.30, (b) NOT present in v4.29 (read
from `/tmp/ml429_names.txt`), (c) not obviously auto-generated, and (d) has >= 2
signature-premises that ARE in v4.29 (so it is solvable from the old corpus).

Emits one JSON line per kept target:
  {"name", "module", "sig", "premises":[v4.29 Mathlib consts in the type]} -/

def autoGen (s : String) : Bool :=
  [".congr_simp", ".injEq", ".sizeOf_spec", ".eq_def", ".eq_1", ".eq_2", ".eq_3",
   ".brecOn", ".rec", ".recOn", ".below", ".noConfusion", "._proof_", ".match_",
   ".casesOn", ".ind", ".fwd", ".binductionOn", ".mk.inj", ".ofNat", ".proof_"].any
    (fun t => (s.splitOn t).length > 1)

run_cmd do
  let env ← getEnv
  -- load v4.29 Mathlib name set
  let oldTxt ← IO.FS.readFile "/tmp/ml429_names.txt"
  let mut old : Std.HashSet Name := {}
  for line in oldTxt.splitOn "\n" do
    let l := line.trim
    if !l.isEmpty then old := old.insert l.toName
  let mut lines : Array String := #[]
  let esc := fun (s : String) => s.replace "\\" "\\\\" |>.replace "\"" "\\\"" |>.replace "\n" " "
  for (name, ci) in env.constants.toList do
    if name.isInternal then continue
    -- theorems only
    let .thmInfo _ := ci | continue
    let some midx := env.getModuleIdxFor? name | continue
    let mod := (env.header.moduleNames[midx.toNat]!).toString
    unless "Mathlib".isPrefixOf mod do continue
    let nameStr := toString name
    if autoGen nameStr then continue
    -- NEW in v4.30: not in v4.29
    if old.contains name then continue
    -- signature-premises available in v4.29
    let prem := ci.type.getUsedConstants.filter (fun d => d != name && old.contains d)
    if prem.size < 2 then continue
    let sig ← (do
      try
        let fmt ← liftCoreM <| Meta.MetaM.run' (Meta.ppExpr ci.type)
        pure (toString fmt)
      catch _ => pure "")
    let premStr := String.intercalate "," (prem.toList.map (fun d => "\"" ++ esc (toString d) ++ "\""))
    let line := "{\"name\":\"" ++ esc nameStr ++ "\",\"module\":\"" ++ esc mod
      ++ "\",\"sig\":\"" ++ esc sig ++ "\",\"premises\":[" ++ premStr ++ "]}"
    lines := lines.push line
  IO.FS.writeFile "/tmp/ml_new_targets.jsonl" (String.intercalate "\n" lines.toList)
  logInfo s!"kept {lines.size} candidate targets"
