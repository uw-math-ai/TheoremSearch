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
import Lean.Class
import Lean.DocString
import Lean.Meta.Instances
import ImportGraph.Graph.Structures
import ImportGraph.Graph.TypeDeps
import ImportGraph.Graph.ProofDeps
import ImportGraph.Graph.TransitiveClosure
public import ImportGraph.Graph.FilterCommon

open Lean

/-!
# Unified Dependency Graph

Combines:
- Structure inheritance and fields
- Type signature dependencies
- Proof and definition implementation dependencies
- Docstring backtick references

Edge Types:
1. **extends**: Structure inheritance
2. **field**: Field/parameter reference
3. **signatureType**: Type appearing in signature
4. **proofCall**: Theorem/lemma invocation
5. **defCall**: Definition invocation
6. **docRef**: Backtick reference in docstring (`` `Name ``)
-/

namespace ImportGraph.Unified

/-- Edge type categorization -/
public inductive EdgeType where
  | extends : EdgeType
  | field : EdgeType
  | signatureType : EdgeType
  | proofCall : EdgeType
  | defCall : EdgeType
  | docRef : EdgeType
  deriving Inhabited, BEq, Hashable, Repr

def EdgeType.color : EdgeType → String
  | .extends => "blue"
  | .field => "cyan"
  | .signatureType => "orange"
  | .proofCall => "green"
  | .defCall => "lime"
  | .docRef => "purple"

def EdgeType.style : EdgeType → String
  | .extends => "solid"
  | .field => "solid"
  | .signatureType => "dashed"
  | .proofCall => "solid"
  | .defCall => "solid"
  | .docRef => "dotted"

def EdgeType.penwidth : EdgeType → Nat
  | .extends => 3
  | .field => 2
  | .signatureType => 1
  | .proofCall => 3
  | .defCall => 2
  | .docRef => 1

def EdgeType.label : EdgeType → String
  | .extends => "extends"
  | .field => "field"
  | .signatureType => "sig"
  | .proofCall => "proof"
  | .defCall => "def"
  | .docRef => "docref"

/-- Declaration type classification for nodes -/
public inductive DeclarationType where
  | structure : DeclarationType
  | class : DeclarationType
  | instance : DeclarationType
  | theorem : DeclarationType
  | definition : DeclarationType
  | opaque : DeclarationType
  | inductive : DeclarationType
  | constructor : DeclarationType
  | axiom : DeclarationType
  | other : DeclarationType
  deriving Inhabited, BEq, Repr

public def DeclarationType.shape : DeclarationType → String
  | .structure | .class => "ellipse"
  | .instance | .definition | .opaque | .axiom => "box"
  | .theorem => "diamond"
  | .inductive | .constructor => "triangle"
  | .other => "ellipse"

public def DeclarationType.fillColor : DeclarationType → String
  | .structure => "#b3d9ff"
  | .class => "#99ccff"
  | .instance => "#ffd9b3"
  | .theorem => "#c1f0c1"
  | .definition => "#e2f9e2"
  | .opaque => "#d9d9e8"
  | .inductive => "#d7b3ff"
  | .constructor => "#edd9ff"
  | .axiom => "#ffb3b3"
  | .other => "#e0e0e0"

public def DeclarationType.label : DeclarationType → String
  | .structure => "struct"
  | .class => "class"
  | .instance => "inst"
  | .theorem => "thm"
  | .definition => "def"
  | .opaque => "opaque"
  | .inductive => "ind"
  | .constructor => "ctor"
  | .axiom => "axiom"
  | .other => "other"

/-- Unified graph structure -/
public structure UnifiedGraph where
  nodes : NameSet
  nodeTypes : NameMap DeclarationType
  nodeModules : NameMap Name  -- name → defining Lean module
  extendsEdges : NameMap (Array Name)
  fieldEdges : NameMap (Array Name)
  signatureEdges : NameMap (Array Name)
  proofEdges : NameMap (Array Name)
  defEdges : NameMap (Array Name)
  docRefEdges : NameMap (Array Name)
  deriving Inhabited

/-- Classify a constant's declaration type -/
def classifyDeclarationType (env : Environment) (name : Name) : DeclarationType :=
  match env.find? name with
  | none => .other
  | some info =>
    if Lean.isClass env name then .class
    else if let some _ := Lean.getStructureInfo? env name then .structure
    else if Lean.isStructure env name then .structure
    else if Lean.Meta.isInstanceCore env name then .instance
    else match info with
      | .thmInfo _               => .theorem
      | .defnInfo _              => .definition
      | .opaqueInfo _ | .quotInfo _ => .opaque
      | .axiomInfo _             => .axiom
      | .inductInfo _            => .inductive
      | .ctorInfo _              => .constructor
      | _                        => .other

def nodesFromMap (graph : NameMap (Array Name)) : NameSet :=
  graph.foldl (fun acc name deps =>
    let acc := acc.insert name
    deps.foldl (fun acc dep => acc.insert dep) acc
  ) ∅

/-!
## Docstring backtick reference extraction

Parses docstrings for `` `Name `` patterns where `Name` is a valid Lean identifier
(letters, digits, `.`, `_`, `'`). Double-backtick code spans (`` ``code`` ``) are
skipped. References are validated against the environment and filtered to
declarations that pass the standard inclusion check.
-/

private def isDocNameChar (c : Char) : Bool :=
  c.isAlphanum || c == '.' || c == '_' || c == '\''

private def skipCodeSpan : List Char → List Char
  | '`' :: '`' :: rest => rest
  | [] => []
  | _ :: rest => skipCodeSpan rest

private def collectName : List Char → String → String × List Char
  | [], s => (s, [])
  | c :: rest, s =>
    if isDocNameChar c then collectName rest (s.push c) else (s, c :: rest)

/-- Extract all `` `Name `` backtick references from a docstring. -/
private def extractDocRefNames (docstring : String) : Array String :=
  let rec go : List Char → Array String → Array String
    | [], acc => acc
    | '`' :: '`' :: rest, acc => go (skipCodeSpan rest) acc
    | '`' :: c :: rest, acc =>
      if c.isAlpha || c == '_' then
        let (name, rest') := collectName (c :: rest) ""
        go rest' (if name.isEmpty then acc else acc.push name)
      else
        go (c :: rest) acc
    | _ :: rest, acc => go rest acc
  partial_fixpoint
  go docstring.toList #[]

private def stringToName (s : String) : Name :=
  if s.isEmpty then .anonymous
  else s.splitOn "." |>.foldl (fun acc part => .str acc part) .anonymous

/--
Build docref edges: for each declaration's docstring, extract all `` `Name ``
backtick references that resolve to known, included declarations.
-/
private def buildDocRefEdges (env : Environment) (includeAll : Bool) :
    CoreM (NameMap (Array Name)) := do
  let mut docRefEdges : NameMap (Array Name) := {}
  for (name, _) in env.constants.toList do
    if !Lean.Environment.shouldIncludeConstant env name includeAll then continue
    if let some docStr ← Lean.findDocString? env name then
      let refStrs := extractDocRefNames docStr
      let mut validRefs : Array Name := #[]
      for refStr in refStrs do
        let refName := stringToName refStr
        if refName != .anonymous && env.contains refName &&
           Lean.Environment.shouldIncludeConstant env refName includeAll &&
           refName != name && !validRefs.contains refName then
          validRefs := validRefs.push refName
      if !validRefs.isEmpty then
        docRefEdges := docRefEdges.insert name validRefs
  return docRefEdges

/--
Build the unified dependency graph.
-/
public def unifiedGraph (env : Environment) (includeAll : Bool := false) : CoreM UnifiedGraph := do

  -- Step 1: Collect structures graph
  IO.eprintln "[Unified] Analyzing structures..."
  let structures ← env.analyzeStructures includeAll

  -- Step 2: Collect type signature graph
  IO.eprintln "[Unified] Analyzing type signatures..."
  let typeDepsGraph ← env.typeDepsGraph includeAll

  -- Step 3: Collect proof dependencies graph
  IO.eprintln "[Unified] Analyzing proof implementations..."
  let proofDepsGraph ← env.proofDepsGraph includeAll

  -- Step 4: Build docref edges from docstring backtick references
  IO.eprintln "[Unified] Extracting docstring references..."
  let docRefEdges ← buildDocRefEdges env includeAll

  -- Step 5: Extract and merge node sets (including docref participants)
  IO.eprintln "[Unified] Merging nodes..."
  let mut allNodes := nodesFromMap structures.extendsEdges
  allNodes := (nodesFromMap structures.fieldEdges).foldl (·.insert ·) allNodes
  allNodes := (nodesFromMap typeDepsGraph).foldl (·.insert ·) allNodes
  allNodes := (nodesFromMap proofDepsGraph).foldl (·.insert ·) allNodes
  allNodes := (nodesFromMap docRefEdges).foldl (·.insert ·) allNodes

  -- Step 6: Classify nodes and record modules
  IO.eprintln s!"[Unified] Classifying {allNodes.size} nodes..."
  let mut nodeTypes : NameMap DeclarationType := {}
  let mut nodeModules : NameMap Name := {}
  for name in allNodes.toList do
    nodeTypes := nodeTypes.insert name (classifyDeclarationType env name)
    let modName : Name := match env.getModuleIdxFor? name with
      | some idx => env.header.moduleNames[idx.toNat]!
      | none => .anonymous
    nodeModules := nodeModules.insert name modName

  -- Step 7: Categorize proof/def edges
  IO.eprintln "[Unified] Categorizing edges..."
  let mut proofEdges : NameMap (Array Name) := {}
  let mut defEdges : NameMap (Array Name) := {}

  for (source, targets) in proofDepsGraph.toList do
    let sourceType := nodeTypes.find? source |>.getD .other
    if sourceType == .theorem then
      proofEdges := proofEdges.insert source targets
    else
      defEdges := defEdges.insert source targets

  return {
    nodes := allNodes
    nodeTypes := nodeTypes
    nodeModules := nodeModules
    extendsEdges := structures.extendsEdges
    fieldEdges := structures.fieldEdges
    signatureEdges := typeDepsGraph
    proofEdges := proofEdges
    defEdges := defEdges
    docRefEdges := docRefEdges
  }

public def UnifiedGraph.totalEdgeCount (g : UnifiedGraph) : Nat :=
  let count (m : NameMap (Array Name)) := m.foldl (fun acc _ deps => acc + deps.size) 0
  count g.extendsEdges + count g.fieldEdges + count g.signatureEdges +
  count g.proofEdges + count g.defEdges + count g.docRefEdges

/-- Get edge count for a specific edge type -/
public def UnifiedGraph.edgeCountByType (g : UnifiedGraph) (et : EdgeType) : Nat :=
  let count (m : NameMap (Array Name)) := m.foldl (fun acc _ deps => acc + deps.size) 0
  match et with
  | .extends => count g.extendsEdges
  | .field => count g.fieldEdges
  | .signatureType => count g.signatureEdges
  | .proofCall => count g.proofEdges
  | .defCall => count g.defEdges
  | .docRef => count g.docRefEdges

end ImportGraph.Unified
