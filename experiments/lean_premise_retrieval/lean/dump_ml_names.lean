import Mathlib
import Lean
open Lean

/-- Dump every non-internal declaration whose defining module is under `Mathlib.`
as one `name<TAB>kind` line. Used to diff the v4.30 decl set against v4.29. -/
run_cmd do
  let env ← getEnv
  let mut lines : Array String := #[]
  for (name, ci) in env.constants.toList do
    if name.isInternal then continue
    let some midx := env.getModuleIdxFor? name | continue
    let mod := (env.header.moduleNames[midx.toNat]!).toString
    unless "Mathlib".isPrefixOf mod do continue
    let kind := match ci with
      | .thmInfo _ => "theorem" | .defnInfo _ => "def"
      | .axiomInfo _ => "axiom" | .inductInfo _ => "inductive"
      | .ctorInfo _ => "ctor"   | .recInfo _ => "rec"
      | .opaqueInfo _ => "opaque" | .quotInfo _ => "quot"
    lines := lines.push (toString name ++ "\t" ++ kind)
  IO.FS.writeFile "/tmp/mathlib430_names.tsv" (String.intercalate "\n" lines.toList)
  logInfo s!"wrote {lines.size} Mathlib decls"
