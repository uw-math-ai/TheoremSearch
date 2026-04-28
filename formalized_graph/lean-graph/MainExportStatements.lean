/-
Copyright (c) 2024 ImportGraph Contributors. All rights reserved.
Released under Apache 2.0 license as described in the file LICENSE.
Authors: ImportGraph Contributors
-/
import Lean
import Lean.Meta.Basic
import Lean.PrettyPrinter
import Lean.Util.PPExt
import Lean.Class
import Lean.DocString
import Lean.Elab.Term
import ImportGraph.Graph.FilterCommon
import ImportGraph.Lean.WithImportModules
import ImportGraph.Util.CurrentModule

/-!
# `lake exe export_statements`

Exports every explicit Lean declaration in the target module as a JSONL file:
```
{"name":"Nat.add_comm","module":"Init.Data.Nat.Basic","decl_type":"theorem",
 "signature":"Nat.add_comm : ∀ (n m : ℕ), n + m = m + n"}
```

Pairs with `unified.db` for LLM-based English definition generation.

## Running via interpreter (for proper notation)

To get `+`, `*`, `^` instead of `instHAdd.hAdd` etc., run via:
```
lake env lean --run MainExportStatements.lean -- --to Mathlib --pretty
```
The `lean` interpreter has unexpanders baked in; the compiled binary does not.
-/

open Lean Meta PrettyPrinter

/-- Escape a string for JSON embedding. -/
private def jsonEscape (s : String) : String :=
  s.foldl (fun acc c =>
    match c with
    | '\\' => acc ++ "\\\\"
    | '"'  => acc ++ "\\\""
    | '\n' => acc ++ "\\n"
    | '\r' => acc ++ "\\r"
    | '\t' => acc ++ "\\t"
    | c    => acc.push c) ""

/-- Classify a declaration kind as a short label. -/
private def declTypeLabel (env : Environment) (name : Name) (info : ConstantInfo) : String :=
  if Lean.isClass env name then "class"
  else if let some _ := Lean.getStructureInfo? env name then "structure"
  else if Lean.isStructure env name then "structure"
  else if Lean.Meta.isInstanceCore env name then "instance"
  else match info with
    | .thmInfo _               => "theorem"
    | .defnInfo _              => "definition"
    | .opaqueInfo _ | .quotInfo _ => "opaque"
    | .axiomInfo _             => "axiom"
    | .inductInfo _            => "inductive"
    | .ctorInfo _              => "constructor"
    | _                        => "other"

/-- Get the root namespace component of a `Name` (e.g. `Mathlib.Algebra.Group` → `Mathlib`). -/
private def nameRoot : Name → Name
  | .str .anonymous s => .str .anonymous s
  | .num .anonymous n => .num .anonymous n
  | .str parent _    => nameRoot parent
  | .num parent _    => nameRoot parent
  | .anonymous       => .anonymous

/--
Decide whether a declaration should appear in the exported statements file.
Matches `shouldIncludeConstant` exactly: doc-gen4 aligned filter.
Pass `includeAll := true` for exhaustive/debug export.
-/
private def shouldIncludeForExport (env : Environment) (name : Name)
    (includeAll : Bool) : Bool :=
  Lean.Environment.shouldIncludeConstant env name includeAll

/--
Try to get the pretty-printed signature string for `name`.

In normal mode, delegates to `ppSignature` (fast, but may output elaborated
instance projections like `instHAdd.hAdd` instead of `+` for some theorems).

In pretty mode (`prettyMode := true`), runs inside `TermElabM` which activates
all notation unexpanders (e.g. `HAdd.hAdd → +`). Requires running via
`lake env lean --run` rather than as a compiled binary.
-/
private def tryGetSignature (name : Name) (ctx : Core.Context) (s : Core.State)
    (prettyMode : Bool := false) : IO (Option String) := do
  try
    if prettyMode then
      -- Run ppSignature inside TermElabM, which is the same context as #check.
      -- This activates the notation unexpanders (e.g. HAdd.hAdd → +).
      let (fmtWithInfos, _) ← (MetaM.run' do
        Lean.Elab.Term.TermElabM.run' do
          withOptions (fun o => o.setBool `pp.fieldNotation false) do
            ppSignature name
      ).toIO ctx s
      return some (fmtWithInfos.fmt.pretty 120)
    else
      let (fmtWithInfos, _) ← (MetaM.run' (ppSignature name)).toIO ctx s
      return some (fmtWithInfos.fmt.pretty 120)
  catch _ => return none

/-- Parse CLI flags from a raw arg list. Supports:
    --to <Module[,Module,...]>  (repeatable)
    --output <path>
    --include-infra
    --include-aux
    --pretty -/
private def parseArgs (args : List String) : IO (Array Name × String × Bool × Bool × Bool) := do
  let arr := args.toArray
  let mut toModules : Array Name := #[]
  let mut outFile := "statements.jsonl"
  let mut includeInfra := false
  let mut includeAll := false
  let mut prettyMode := false
  let mut i := 0
  while i < arr.size do
    let arg := arr[i]!
    if arg == "--to" && i + 1 < arr.size then
      let modStr := arr[i + 1]!
      let names := modStr.splitOn "," |>.toArray |>.filterMap fun s =>
        let t := s.trimAscii; if t.isEmpty then none else some t.toName
      toModules := toModules ++ names
      i := i + 2
    else if arg == "--output" && i + 1 < arr.size then
      outFile := arr[i + 1]!
      i := i + 2
    else if arg == "--include-infra" then
      includeInfra := true; i := i + 1
    else if arg == "--include-aux" then
      includeAll := true; i := i + 1
    else if arg == "--pretty" then
      prettyMode := true; i := i + 1
    else
      i := i + 1
  return (toModules, outFile, includeInfra, includeAll, prettyMode)

def exportStatements (args : List String) : IO UInt32 := do
  let (toRaw, outFile, includeInfra, includeAll, prettyMode) ← parseArgs args
  let to ← if toRaw.isEmpty then
    pure #[← ImportGraph.getCurrentModule]
  else
    pure toRaw

  initSearchPath (← findSysroot)

  unsafe Lean.enableInitializersExecution
  -- loadExts := true is required so finalizePersistentExtensions runs and populates
  -- appUnexpanderAttribute (and other extensions) from .olean entries.
  -- Without it, ppSignature cannot restore +, *, ^ notation.
  let env ← importModules (to.map ({module := ·})) {} (trustLevel := 1024) (loadExts := true)
  let ctx   : Core.Context := { options := {}, fileName := "<input>", fileMap := default }
  let state : Core.State   := { env }

  -- Positive module filter: allow root namespaces of --to modules plus core libraries.
  -- Always includes Init (Lean core), Std (standard library), Lean (core types),
  -- and Batteries (extra lemmas). Use --include-infra to also get Qq, Plausible, etc.
  let allowedRoots : Array Name :=
    (to.map nameRoot) ++ [`Init, `Std, `Lean, `Batteries]

  let handle ← IO.FS.Handle.mk ⟨outFile⟩ IO.FS.Mode.write
  let mut count   := 0
  let mut skipped := 0

  for (name, constInfo) in env.constants.toList do
    -- Skip anonymous, internal, macro-scoped names
    if name == .anonymous || name.isInternal || name.hasMacroScopes then
      skipped := skipped + 1
    else
      if !shouldIncludeForExport env name includeAll then
        skipped := skipped + 1
      else
        -- Resolve defining module
        let modName : Name := match env.getModuleIdxFor? name with
          | some idx => env.header.moduleNames[idx.toNat]!
          | none     => .anonymous
        let modStr := modName.toString

        -- Positive module filter: skip unless module root is in allowedRoots.
        let isAllowed := includeInfra || allowedRoots.any (fun r => r.isPrefixOf modName)
        if !isAllowed then
          skipped := skipped + 1
        else
          -- Pretty-print the signature
          let sigOpt ← tryGetSignature name ctx state prettyMode
          match sigOpt with
          | none =>
            skipped := skipped + 1
          | some sig =>
            let dtype     := declTypeLabel env name constInfo
            let docstring := ((← Lean.findDocString? env name).getD "")
            let line  := s!"\{\"name\":\"{jsonEscape name.toString}\"," ++
                          s!"\"module\":\"{jsonEscape modStr}\"," ++
                          s!"\"decl_type\":\"{dtype}\"," ++
                          s!"\"signature\":\"{jsonEscape sig}\"," ++
                          s!"\"docstring\":\"{jsonEscape docstring}\"}"
            handle.putStrLn line
            count := count + 1
            if count % 10000 == 0 then
              IO.eprintln s!"[ExportStatements] {count} exported..."

  IO.eprintln s!"[ExportStatements] Done: {count} exported, {skipped} skipped → {outFile}"
  return 0

/-- `lake exe export_statements` or `lake env lean --run MainExportStatements.lean` -/
def main (args : List String) : IO UInt32 :=
  exportStatements args
