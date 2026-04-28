/-
Copyright (c) 2024 ImportGraph Contributors. All rights reserved.
Released under Apache 2.0 license as described in the file LICENSE.
Authors: ImportGraph Contributors
-/
module

public import Lean.Environment
public import Lean.CoreM
public import ImportGraph.Graph.FilterCommon
import Lean.Data.NameMap.Basic
import Lean.Meta.Match.MatcherInfo

open Lean Meta

/-!
# Proof Dependency Graph (Logic Mode)

Constructs a dependency graph based on proof bodies and definition values.
Unlike type dependencies, this extracts constants from the actual implementations.

For theorems: dependencies from the proof body
For definitions: dependencies from the definition body
-/

namespace Lean.Environment

private def applyTransitiveClosureChunked (env : Environment) (deps : Array Name)
    (includeAll : Bool := false) : CoreM (Array Name) :=
  applyTransitiveClosureForProofDeps env deps includeAll

-- Stream proof-deps graph directly to file handle
public def proofDepsGraphStreaming (env : Environment)
    (handle : IO.FS.Handle)
    (includeAll : Bool := false) : CoreM Unit := do
  let mut processedCount := 0
  let mut skippedCount := 0
  let mut edgeCount := 0
  let mut isolatedNodes := 0
  let allConstants := env.constants.toList
  let totalCount := allConstants.length

  IO.eprintln "Starting proof-deps graph generation (streaming)..."

  for (name, info) in allConstants do
    processedCount := processedCount + 1

    if processedCount % 5000 == 0 then
      IO.eprintln s!"Processing constant {processedCount}/{totalCount}: {name}"

    if !shouldIncludeConstantInProofDeps env name includeAll then
      skippedCount := skippedCount + 1
      continue

    let deps : Array Name := match info with
      | .thmInfo val => val.value.getUsedConstants
      | .defnInfo val =>
        -- `irreducible_def` (Mathlib.Tactic.IrreducibleDef) wraps the actual body
        -- in an opaque Subtype, so val.value is just `Subtype.val wrapped` and
        -- getUsedConstants returns only the opaque wrapper, not the real body.
        -- The command also generates a `{name}_def` sibling theorem whose TYPE is
        -- `name = actual_body_expr`. Walking that type recovers the hidden deps.
        let direct := val.value.getUsedConstants
        let irredDeps : Array Name :=
          match name with
          | .str pre s =>
            match env.find? (.str pre (s ++ "_def")) with
            | some (.thmInfo defLemma) => defLemma.type.getUsedConstants
            | _ => #[]
          | _ => #[]
        (direct ++ irredDeps).toList.eraseDups.toArray
      | .axiomInfo _ => #[]
      | _ => #[]

    let processedDeps ← applyTransitiveClosureForProofDeps env deps includeAll

    if processedDeps.isEmpty then
      handle.putStrLn s!"  \"{name}\";"
      isolatedNodes := isolatedNodes + 1
    else
      for dep in processedDeps do
        handle.putStrLn s!"  \"{dep}\" -> \"{name}\";"
        edgeCount := edgeCount + 1

      if edgeCount % 1000 == 0 then
        _ ← handle.flush

  IO.eprintln s!"Completed: {processedCount} constants iterated, {skippedCount} skipped, {edgeCount} edges, {isolatedNodes} isolated nodes"

/--
Build a proof dependencies graph from the Lean environment.
-/
public def proofDepsGraph (env : Environment) (includeAll : Bool := false) :
    CoreM (NameMap (Array Name)) := do
  let mut graph : NameMap (Array Name) := {}
  let mut processedCount := 0
  let mut skippedCount := 0

  IO.eprintln "Starting proof-deps graph generation..."

  for (name, info) in env.constants.toList do
    processedCount := processedCount + 1

    if processedCount % 5000 == 0 then
      IO.eprintln s!"Processing constant {processedCount}: {name}"

    if !shouldIncludeConstantInProofDeps env name includeAll then
      skippedCount := skippedCount + 1
      continue

    match info with
    | .thmInfo val =>
      let deps := val.value.getUsedConstants
      let processedDeps ← applyTransitiveClosureForProofDeps env deps includeAll
      graph := graph.insert name processedDeps
    | .defnInfo val =>
      -- See comment in proofDepsGraphStreaming: recover irreducible_def body deps
      -- from the auto-generated `{name}_def` sibling theorem's type.
      let direct := val.value.getUsedConstants
      let irredDeps : Array Name :=
        match name with
        | .str pre s =>
          match env.find? (.str pre (s ++ "_def")) with
          | some (.thmInfo defLemma) => defLemma.type.getUsedConstants
          | _ => #[]
        | _ => #[]
      let allDeps := (direct ++ irredDeps).toList.eraseDups.toArray
      let processedDeps ← applyTransitiveClosureForProofDeps env allDeps includeAll
      graph := graph.insert name processedDeps

    | .axiomInfo _ =>
      graph := graph.insert name #[]

    | _ =>
      continue

  IO.eprintln s!"Completed: {processedCount} constants iterated, {skippedCount} skipped"
  return graph

end Lean.Environment
