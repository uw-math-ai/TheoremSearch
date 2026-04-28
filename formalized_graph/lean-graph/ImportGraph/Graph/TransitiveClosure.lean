/-
Copyright (c) 2023 Kim Morrison. All rights reserved.
Released under Apache 2.0 license as described in the file LICENSE.
Authors: Kim Morrison, Paul Lezeau
-/
module

public import Lean.Data.NameMap.Basic

/-!
# Transitive closure and reduction of a graph

A "graph" in this context is a `NameMap (Array Name)`.
-/

namespace Lean.NameMap

/--
Compute the transitive closure of an import graph.
Uses an iterative approach with a stack to avoid stack overflow.
-/
public def transitiveClosure (m : NameMap (Array Name)) : NameMap NameSet := Id.run do
  let mut result : NameMap NameSet := {}
  let nodes := m.toList.map (·.1)
  
  for startNode in nodes do
    if result.contains startNode then continue
    
    -- DFS stack: (node, children_to_process)
    let mut stack : List (Name × List Name) := [(startNode, (m.find? startNode).getD #[] |>.toList)]
    let mut visited_in_current_dfs : NameSet := {startNode}
    
    while !stack.isEmpty do
      match stack with
      | [] => break
      | (u, []) :: tail =>
        -- Finished u, compute its closure from children
        stack := tail
        let deps := (m.find? u).getD #[]
        let mut uClosure : NameSet := .ofList deps.toList
        for d in deps do
          uClosure := uClosure.union (result.find? d |>.getD {})
        result := result.insert u uClosure
      | (u, v :: vs) :: tail =>
        -- Process child v of u
        stack := (u, vs) :: tail
        if result.contains v then
          continue
        if visited_in_current_dfs.contains v then
          -- Cycle detected or already visited in this DFS branch
          continue
        
        visited_in_current_dfs := visited_in_current_dfs.insert v
        stack := (v, (m.find? v).getD #[] |>.toList) :: stack
        
  return result

/--
Compute the transitive reduction of an import graph.
Removes an edge (A -> C) if there is another path from A to C through B.
-/
public def transitiveReduction (m : NameMap (Array Name)) : NameMap (Array Name) :=
  let closure := transitiveClosure m
  m.foldl (fun res n deps =>
    -- For each dependency d of n, check if it's reachable from any other dependency d'
    let reducedDeps := deps.filter (fun d =>
      !deps.any (fun d' => d != d' && ((closure.find? d').getD {}).contains d)
    )
    res.insert n reducedDeps
  ) {}

end Lean.NameMap
