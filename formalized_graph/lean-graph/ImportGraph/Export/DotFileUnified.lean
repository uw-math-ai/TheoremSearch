/-
Copyright (c) 2024 ImportGraph Contributors. All rights reserved.
Released under Apache 2.0 license as described in the file LICENSE.
Authors: ImportGraph Contributors
-/
module

public import ImportGraph.Graph.Unified
open Lean
open ImportGraph.Unified

namespace ImportGraph.Unified.Export

/-- Write companion nodes CSV: name,decl_type,module -/
private def writeNodesCSV (g : UnifiedGraph) (csvPath : String) : IO Unit := do
  IO.eprintln s!"[Unified] Writing nodes CSV to {csvPath}"
  let csv ← IO.FS.Handle.mk ⟨csvPath⟩ IO.FS.Mode.write
  csv.putStrLn "name,decl_type,module"
  for (name, declType) in g.nodeTypes.toList do
    let modName := (g.nodeModules.find? name |>.getD .anonymous).toString
    csv.putStrLn s!"\"{name}\",\"{declType.label}\",\"{modName}\""

/-- Write unified graph to DOT format with categorized edges -/
public def writeUnifiedGraphToFile
    (g : UnifiedGraph)
    (filePath : System.FilePath)
    (allowedEdgeTypes : Option (Std.HashSet String) := none) : IO Unit := do
  let allow (label : String) : Bool :=
    match allowedEdgeTypes with
    | none => true
    | some s => s.contains label

  IO.eprintln s!"[Unified] Writing unified graph to {filePath}"

  -- Write companion nodes CSV alongside the DOT file
  let dotStr := filePath.toString
  let csvStr := if dotStr.endsWith ".dot"
                then (dotStr.take (dotStr.length - 4)).toString ++ "_nodes.csv"
                else dotStr ++ "_nodes.csv"
  writeNodesCSV g csvStr

  let handle ← IO.FS.Handle.mk filePath IO.FS.Mode.write

  -- Write header
  handle.putStrLn "digraph unified_graph {"

  -- Write nodes
  IO.eprintln "[Unified DOT] Writing nodes..."
  for (name, declType) in g.nodeTypes.toList do
    let shape := declType.shape
    let fillColor := declType.fillColor
    handle.putStrLn s!"  \"{name}\" [shape={shape}, style=filled, fillcolor=\"{fillColor}\"];"

  -- Write extends edges (blue)
  if allow "extends" then
    IO.eprintln "[Unified DOT] Writing extends edges..."
    for (source, targets) in g.extendsEdges.toList do
      for target in targets do
        handle.putStrLn s!"  \"{target}\" -> \"{source}\" [color=\"blue\", penwidth=3, kind=extends];"

  -- Write field edges (cyan)
  if allow "field" then
    IO.eprintln "[Unified DOT] Writing field edges..."
    for (source, targets) in g.fieldEdges.toList do
      for target in targets do
        handle.putStrLn s!"  \"{target}\" -> \"{source}\" [color=\"cyan\", penwidth=2, kind=field];"

  -- Write signature edges (orange)
  if allow "sig" then
    IO.eprintln "[Unified DOT] Writing signature edges..."
    for (source, targets) in g.signatureEdges.toList do
      for target in targets do
        handle.putStrLn s!"  \"{target}\" -> \"{source}\" [color=\"orange\", penwidth=1, style=dashed, kind=sig];"

  -- Write proof edges (green)
  if allow "proof" then
    IO.eprintln "[Unified DOT] Writing proof edges..."
    for (source, targets) in g.proofEdges.toList do
      for target in targets do
        handle.putStrLn s!"  \"{target}\" -> \"{source}\" [color=\"green\", penwidth=3, kind=proof];"

  -- Write def edges (lime)
  if allow "def" then
    IO.eprintln "[Unified DOT] Writing def edges..."
    for (source, targets) in g.defEdges.toList do
      for target in targets do
        handle.putStrLn s!"  \"{target}\" -> \"{source}\" [color=\"#32CD32\", penwidth=2, kind=def];"

  -- Write docref edges (purple, dotted)
  if allow "docref" then
    IO.eprintln "[Unified DOT] Writing docref edges..."
    for (source, targets) in g.docRefEdges.toList do
      for target in targets do
        handle.putStrLn s!"  \"{target}\" -> \"{source}\" [color=\"purple\", penwidth=1, style=dotted, kind=docref];"

  -- Write footer
  handle.putStrLn "}"
  _ ← handle.flush

  -- Statistics
  let totalEdges := UnifiedGraph.totalEdgeCount g
  IO.eprintln s!"[Unified] Wrote {g.nodes.toList.length} nodes and {totalEdges} edges"
  IO.eprintln s!"[Unified] Edge breakdown:"
  IO.eprintln s!"  - Extends:   {UnifiedGraph.edgeCountByType g .extends}"
  IO.eprintln s!"  - Field:     {UnifiedGraph.edgeCountByType g .field}"
  IO.eprintln s!"  - Signature: {UnifiedGraph.edgeCountByType g .signatureType}"
  IO.eprintln s!"  - Proof:     {UnifiedGraph.edgeCountByType g .proofCall}"
  IO.eprintln s!"  - Def:       {UnifiedGraph.edgeCountByType g .defCall}"
  IO.eprintln s!"  - DocRef:    {UnifiedGraph.edgeCountByType g .docRef}"

end ImportGraph.Unified.Export
