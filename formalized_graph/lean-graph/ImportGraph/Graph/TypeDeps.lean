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
import Lean.Structure

open Lean Meta

/-!
# Type Dependency Graph (Blueprint Mode)

This module constructs a dependency graph based on type signatures.
For each constant, we extract all constants mentioned in its type signature.
-/

namespace Lean.Environment

/--
Extract type dependencies: all constants mentioned in the type signature.
-/
private def getTypeDependencies (_env : Environment) (_name : Name) (info : ConstantInfo) : Array Name :=
  info.type.getUsedConstants

/-- Build type dependency graph based on constant type signatures. -/
public def typeDepsGraph (env : Environment) (includeAll : Bool := false) :
    CoreM (NameMap (Array Name)) := do
  let mut graph : NameMap (Array Name) := {}

  for (name, info) in env.constants.toList do
    if shouldIncludeConstant env name includeAll then
      let deps := getTypeDependencies env name info
      let processedDeps ← applyTransitiveClosure env deps includeAll
      graph := graph.insert name processedDeps

  return graph

end Lean.Environment
