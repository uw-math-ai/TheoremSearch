import BrownianMotion
import Lean
open Lean Lean.Elab.Command Lean.PrettyPrinter

/-- Dump every declaration DEFINED IN the BrownianMotion library (module-based
filter, so it excludes Mathlib/core deps) as one JSON line:
  {"name", "kind", "module", "sig", "lib_deps":[...]}
`sig` is the pretty-printed signature; `lib_deps` are the constants in the
type that are themselves library decls (the library-specific premises). -/
run_cmd do
  let env ← getEnv
  -- names of all decls defined in BrownianMotion modules
  let mut libNames : Std.HashSet Name := {}
  for (name, _) in env.constants.toList do
    if let some midx := env.getModuleIdxFor? name then
      let mod := (env.header.moduleNames[midx.toNat]!).toString
      if "BrownianMotion".isPrefixOf mod then
        libNames := libNames.insert name
  let mut lines : Array String := #[]
  for (name, ci) in env.constants.toList do
    if name.isInternal then continue
    let some midx := env.getModuleIdxFor? name | continue
    let mod := (env.header.moduleNames[midx.toNat]!).toString
    unless "BrownianMotion".isPrefixOf mod do continue
    let kind := match ci with
      | .thmInfo _ => "theorem" | .defnInfo _ => "def"
      | .axiomInfo _ => "axiom" | _ => "other"
    let sig ← (do
      try
        let fmt ← liftCoreM <| Meta.MetaM.run' (Meta.ppExpr ci.type)
        pure (toString fmt)
      catch _ => pure "")
    -- intra-library type dependencies
    let deps := ci.type.getUsedConstants.filter (fun d => libNames.contains d && d != name)
    let depStr := String.intercalate "," (deps.toList.map (fun d => "\"" ++ toString d ++ "\""))
    let esc := fun (s : String) => s.replace "\\" "\\\\" |>.replace "\"" "\\\"" |>.replace "\n" " "
    let line := "{\"name\":\"" ++ esc (toString name) ++ "\",\"kind\":\"" ++ kind
      ++ "\",\"module\":\"" ++ esc mod ++ "\",\"sig\":\"" ++ esc sig
      ++ "\",\"lib_deps\":[" ++ depStr ++ "]}"
    lines := lines.push line
  IO.FS.writeFile "/tmp/bm_decls.jsonl" (String.intercalate "\n" lines.toList)
  logInfo s!"wrote {lines.size} library decls to /tmp/bm_decls.jsonl"
