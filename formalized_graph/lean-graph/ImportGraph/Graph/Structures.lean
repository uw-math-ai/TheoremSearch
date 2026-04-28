/-
Copyright (c) 2024 ImportGraph Contributors. All rights reserved.
Released under Apache 2.0 license as described in the file LICENSE.
Authors: ImportGraph Contributors
-/
module

public import Lean.Environment
public import Lean.CoreM
import Lean.Data.NameMap.Basic
import Lean.Structure
public import ImportGraph.Graph.FilterCommon

open Lean

/-!
# Structure and Typeclass Relationship Graph

Captures two types of relationships:
1. **Extends**: Explicit inheritance (A extends B)
2. **Field**: Semantic composition (A has a field/parameter of type B)
-/

namespace Lean.Environment

/-- Result of structure analysis -/
public structure StructureAnalysis where
  extendsEdges : NameMap (Array Name)
  fieldEdges : NameMap (Array Name)
  allNodes : NameSet
  deriving Inhabited

/--
Get the parent structures of a structure/class by examining its structure info.
-/
private def getParentStructures (env : Environment) (structName : Name) : Array Name := Id.run do
  if let some info := Lean.getStructureInfo? env structName then
    return info.parentInfo.map (·.structName)
  else
    return #[]

/--
Extract structure/class names from an expression.
-/
private def extractStructuresFromExpr (env : Environment) (e : Expr) : NameSet :=
  let rec walk (expr : Expr) (acc : NameSet) : NameSet :=
    match expr with
    | Expr.const n _ =>
      -- Capture type-level documented constants in field expressions.
      -- Includes structures, inductives, and defs (e.g. Set, Exists, Multiset).
      -- Excludes theorems and constructors: these appear in proof-valued fields
      -- and dependent type literals (e.g. Bool.true, Nat.succ) but are noise
      -- for the purpose of understanding a structure's field types.
      if shouldIncludeConstant env n &&
         !(env.find? n matches some (.thmInfo _)) &&
         !(env.find? n matches some (.ctorInfo _)) then
        acc.insert n
      else
        acc
    | Expr.app f a =>
      walk a (walk f acc)
    | Expr.forallE _ t b _ =>
      walk b (walk t acc)
    | Expr.lam _ t b _ =>
      walk b (walk t acc)
    | _ => acc
  walk e ∅

/--
Extract field/parameter dependencies from a structure's fields, including inherited ones.
Uses `getStructureFieldsFlattened` (with `includeSubobjectFields := false`) so that
parent subobject fields (`toFoo`) are skipped but all leaf fields — own and inherited —
are visited. Each field's projection function type is walked to find structure references.
-/
private def getFieldDependencies (env : Environment) (structName : Name) : Array Name := Id.run do
  let fields := getStructureFieldsFlattened env structName (includeSubobjectFields := false)
  let mut result : NameSet := {}
  for fieldName in fields do
    if let some finfo := getFieldInfo? env structName fieldName then
      if let some projConstInfo := env.find? finfo.projFn then
        let deps := extractStructuresFromExpr env projConstInfo.type
        for dep in deps do
          if dep != structName then
            result := result.insert dep
  return result.toArray

/--
Build the structure/typeclass relationship graph, distinguishing between
inheritance (extends) and composition (fields).
-/
public def analyzeStructures (env : Environment) (includeAll : Bool := false) : CoreM StructureAnalysis := do
  let mut extendsEdges : NameMap (Array Name) := {}
  let mut fieldEdges : NameMap (Array Name) := {}
  let mut allNodes : NameSet := {}

  for (name, _) in env.constants.toList do
    if !shouldIncludeConstant env name includeAll then continue

    if let some _sinfo := Lean.getStructureInfo? env name then
      allNodes := allNodes.insert name

      -- 1. Inheritance edges
      let parents := getParentStructures env name
      let filteredParents ← applyTransitiveClosure env parents includeAll
      if filteredParents.size > 0 then
        extendsEdges := extendsEdges.insert name filteredParents
        for p in filteredParents do allNodes := allNodes.insert p

      -- 2. Field dependencies
      let fields := getFieldDependencies env name
      let filteredFields ← applyTransitiveClosure env fields includeAll
      if filteredFields.size > 0 then
        fieldEdges := fieldEdges.insert name filteredFields
        for f in filteredFields do allNodes := allNodes.insert f

  return { extendsEdges := extendsEdges, fieldEdges := fieldEdges, allNodes := allNodes }

/-- Compatibility wrapper for the old structuresGraph API -/
public def structuresGraph (env : Environment) (includeAll : Bool := false) : CoreM (NameMap (Array Name)) := do
  let analysis ← analyzeStructures env includeAll
  let mut combined : NameMap (Array Name) := {}

  -- Initialize with all nodes found (including leaf nodes)
  for name in analysis.allNodes.toList do
    combined := combined.insert name #[]

  -- Add extends edges
  for (name, parents) in analysis.extendsEdges.toList do
    combined := combined.insert name parents

  -- Merge field edges
  for (name, fields) in analysis.fieldEdges.toList do
    let existing := combined.find? name |>.getD #[]
    combined := combined.insert name ((existing ++ fields).toList.eraseDups.toArray)

  return combined

end Lean.Environment
