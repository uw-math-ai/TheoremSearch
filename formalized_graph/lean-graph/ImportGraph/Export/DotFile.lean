/-
Copyright (c) 2023 Kim Morrison. All rights reserved.
Released under Apache 2.0 license as described in the file LICENSE.
Authors: Kim Morrison, Jon Eugster
-/
module

public import Lean.Data.NameMap.Basic

open Lean

/--
Helper which only returns `true` if the `module` is provided and the name `n` lies
inside it.
 -/
private def isInModule (module : Option Name) (n : Name) := match module with
  | some m => m.isPrefixOf n
  | none => false

/--
Write an import graph directly to a file handle in ".dot" format.
This streaming version avoids building the entire string in memory,
which is important for large graphs (1M+ edges).
-/
public def writeDotGraph
    (handle : IO.FS.Handle)
    (graph : NameMap (Array Name))
    (unused : NameSet := ∅)
    (header := "import_graph")
    (markedPackage : Option Name := none)
    (withSorry : NameSet := ∅)
    (directDeps : NameSet := ∅)
    (from_ to : NameSet := ∅) : IO Unit := do
  let opening := s!"digraph \"{header}\" " ++ "{"
  handle.putStrLn opening
  
  -- Build all content in a single large buffer, then write in one go
  -- This is more efficient than thousands of small putStr calls
  let mut buffer : String := ""
  let mut lineCount := 0
  let mut partCount := 0
  
  for (n, is) in graph do
    let shape := if from_.contains n then "invhouse" else if to.contains n then "house" else "ellipse"
    let nodeLine := if markedPackage.isSome ∧ directDeps.contains n then
      let fill := if withSorry.contains n then
          "#ffd700"
        else if unused.contains n then
          "#e0e0e0"
        else
          "white"
      s!"  \"{n}\" [style=filled, fontcolor=\"#4b762d\", color=\"#71b144\", fillcolor=\"{fill}\", penwidth=2, shape={shape}];\n"
    else if withSorry.contains n then
      s!"  \"{n}\" [style=filled, fillcolor=\"#ffd700\", shape={shape}];\n"
    else if unused.contains n then
      s!"  \"{n}\" [style=filled, fillcolor=\"#e0e0e0\", shape={shape}];\n"
    else if isInModule markedPackage n then
      s!"  \"{n}\" [style=filled, fillcolor=\"#96ec5b\", shape={shape}];\n"
    else
      s!"  \"{n}\" [shape={shape}];\n"
    
    buffer := buffer ++ nodeLine
    
    -- Then add edges
    for i in is do
      let edgeLine := if isInModule markedPackage n then
        if isInModule markedPackage i then
          s!"  \"{i}\" -> \"{n}\" [weight=100];\n"
        else
          s!"  \"{i}\" -> \"{n}\" [penwidth=2, color=\"#71b144\"];\n"
      else
        s!"  \"{i}\" -> \"{n}\";\n"
      buffer := buffer ++ edgeLine
    
    lineCount := lineCount + is.size + 1
    
    -- Write buffer when it reaches ~10MB to prevent unbounded memory growth
    if buffer.length > 10_000_000 then
      handle.putStr buffer
      partCount := partCount + 1
      if partCount % 5 == 0 then
        IO.eprintln s!"[DEBUG-WRITE] Wrote {partCount} parts ({partCount * 10}MB+ so far)"
      _ ← handle.flush
      buffer := ""
  
  -- Write any remaining buffered content
  if buffer.length > 0 then
    handle.putStr buffer
    _ ← handle.flush
  
  handle.putStrLn "}"
  _ ← handle.flush

/--
Write an import graph, represented as a `NameMap (Array Name)` to the ".dot" graph format.
* Nodes in the `unused` set will be shaded light gray.
* If `markedPackage` is provided:
  * Nodes which start with the `markedPackage` will be highlighted in green and drawn closer together.
  * Edges from `directDeps` into the module are highlighted in green
  * Nodes in `directDeps` are marked with a green border and green text.
  * Nodes in `withSorry` are highlighted in gold.

Note: For very large graphs (1M+ edges), consider using `writeDotGraph` instead
to stream directly to a file and avoid memory issues.
-/
public def asDotGraph
    (graph : NameMap (Array Name))
    (unused : NameSet := ∅)
    (header := "import_graph")
    (markedPackage : Option Name := none)
    (withSorry : NameSet := ∅)
    (directDeps : NameSet := ∅)
    (from_ to : NameSet := ∅):
    String := Id.run do
  -- Build string incrementally to avoid memory issues with very large graphs
  let mut result := s!"digraph \"{header}\" " ++ "{\n"
  for (n, is) in graph do
    let shape := if from_.contains n then "invhouse" else if to.contains n then "house" else "ellipse"
    if markedPackage.isSome ∧ directDeps.contains n then
      -- note: `fillcolor` defaults to `color` if not specified
      let fill := if withSorry.contains n then
          "#ffd700"
        else if unused.contains n then
          "#e0e0e0"
        else
          "white"
      result := result ++ s!"  \"{n}\" [style=filled, fontcolor=\"#4b762d\", color=\"#71b144\", fillcolor=\"{fill}\", penwidth=2, shape={shape}];\n"
    else if withSorry.contains n then
      result := result ++ s!"  \"{n}\" [style=filled, fillcolor=\"#ffd700\", shape={shape}];\n"
    else if unused.contains n then
      result := result ++ s!"  \"{n}\" [style=filled, fillcolor=\"#e0e0e0\", shape={shape}];\n"
    else if isInModule markedPackage n then
      -- mark node
      result := result ++ s!"  \"{n}\" [style=filled, fillcolor=\"#96ec5b\", shape={shape}];\n"
    else
      result := result ++ s!"  \"{n}\" [shape={shape}];\n"
    -- Then add edges
    for i in is do
      if isInModule markedPackage n then
        if isInModule markedPackage i then
          -- draw the main project close together
          result := result ++ s!"  \"{i}\" -> \"{n}\" [weight=100];\n"
        else
          -- mark edges into the main project
          result := result ++ s!"  \"{i}\" -> \"{n}\" [penwidth=2, color=\"#71b144\"];\n"
      else
        result := result ++ s!"  \"{i}\" -> \"{n}\";\n"
  result := result ++ "}"
  return result
