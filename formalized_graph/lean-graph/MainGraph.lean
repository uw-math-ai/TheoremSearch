module

public import Cli.Basic
import ImportGraph.Export.DotFile
import ImportGraph.Export.Gexf
import ImportGraph.Export.DotFileUnified
import ImportGraph.Graph.Filter
import ImportGraph.Graph.TransitiveClosure
import ImportGraph.Graph.TypeDeps
import ImportGraph.Graph.ProofDeps
import ImportGraph.Graph.Structures
import ImportGraph.Graph.Unified
import ImportGraph.Imports.ImportGraph
import ImportGraph.Imports.RequiredModules
import ImportGraph.Lean.Name
import ImportGraph.Util.CurrentModule
import ImportGraph.Util.FindSorry
import Lean.Data.NameMap.AdditionalOperations

/-!
# `lake exe graph`

This is a replacement for Lean 3's `leanproject import-graph` tool.
-/

open Cli

open Lean Core System ImportGraph

open IO.FS IO.Process Name in
/-- Implementation of the import graph command line program. -/
def importGraphCLI (args : Cli.Parsed) : IO UInt32 := do
  -- file extensions that should be created
  let extensions : Std.HashSet String := match args.variableArgsAs! String with
    | #[] => {"dot"}
    | outputs => outputs.foldl (fun acc (o : String) =>
      match FilePath.extension o with
       | none => acc.insert "dot"
       | some "gexf" => acc.insert "gexf"
       | some "html" => acc.insert "gexf"
       -- currently all other formats are handled by passing the `.dot` file to
       -- graphviz
       | some _ => acc.insert "dot" ) {}

  let to ← match args.flag? "to" with
  | some to => pure <| to.as! (Array ModuleName)
  | none => pure #[← getCurrentModule]
  let from? : Option (Array Name) := match args.flag? "from" with
  | some fr => some <| fr.as! (Array ModuleName)
  | none => none
  initSearchPath (← findSysroot)

  let includeAll := args.hasFlag "include-aux"

  unsafe Lean.enableInitializersExecution
  let outFiles ← try unsafe withImportModules (to.map ({module := ·})) {} (trustLevel := 1024) fun env => do
    let toModule := ImportGraph.getModule to[0]!

    -- Select graph mode based on --mode flag
    -- Track whether we're in constant-level mode (vs module-level)
    let (graphInit, isConstantLevel, isUnifiedMode) ← match args.flag? "mode" with
      | some modeFlag =>
        let mode := (modeFlag.as! String).toLower

        match mode with
        | "unified" =>
          pure ({}, true, true)
        | "type-deps" | "blueprint" =>
          let ctx := { options := {}, fileName := "<input>", fileMap := default }
          let state := { env }
          let g ← Prod.fst <$> (CoreM.toIO (env.typeDepsGraph includeAll) ctx state)
          pure (g, true, false)
        | "proof-deps" | "logic" =>
          let ctx := { options := {}, fileName := "<input>", fileMap := default }
          let state := { env }
          let g ← Prod.fst <$> (CoreM.toIO (env.proofDepsGraph includeAll) ctx state)
          pure (g, true, false)
        | "hierarchy" | "triangles" | "structures" =>
          let ctx := { options := {}, fileName := "<input>", fileMap := default }
          let state := { env }
          let g ← Prod.fst <$> (CoreM.toIO (env.structuresGraph includeAll) ctx state)
          pure (g, true, false)
        | "imports" | "" =>
          pure (env.importGraph, false, false)
        | other =>
          throw <| IO.userError s!"Unknown graph mode: '{other}'. Valid modes: imports, type-deps, proof-deps, hierarchy, structures, unified"
      | none => pure (env.importGraph, false, false)
    
    -- Handle unified mode separately since it has a different type
    if isUnifiedMode then
      let ctx := { options := {}, fileName := "<input>", fileMap := default }
      let state := { env }
      let unifiedGraph ← Prod.fst <$> (CoreM.toIO (ImportGraph.Unified.unifiedGraph env includeAll) ctx state)

      -- Parse --edge-types flag
      let allowedEdgeTypes : Option (Std.HashSet String) :=
        match args.flag? "edge-types" with
        | none => none
        | some flag =>
          let types := (flag.as! String).splitOn ","
          some <| types.foldl (fun acc t => acc.insert t.trimAscii.toString) {}

      -- Write unified DOT file
      if extensions.contains "dot" then
        let dotOutputs := match args.variableArgsAs! String with
          | #[] => #["unified_graph.dot"]
          | outputs => outputs.filter (fun o =>
              match (o : FilePath).extension with
              | none | some "dot" => true
              | _ => false)
        for output in dotOutputs do
          ImportGraph.Unified.Export.writeUnifiedGraphToFile unifiedGraph output allowedEdgeTypes
      
      return {}  -- Return empty for GEXF (unified doesn't support GEXF yet)
    
    let mut graph := graphInit
    let modulesWithSorry := if args.hasFlag "mark-sorry" then ImportGraph.allModulesWithSorry env else ∅

    if let Option.some f := from? then
      graph := graph.downstreamOf (NameSet.ofArray f)
    
    let unused ←
      match args.flag? "to" with
      | some _ =>
        let init := NameSet.ofArray to
        let ctx := { options := {}, fileName := "<input>", fileMap := default }
        let state := { env }
        let used ← Prod.fst <$> (CoreM.toIO (env.transitivelyRequiredModules' to.toList) ctx state)
        let used := used.foldl (init := init) (fun s _ t => s ∪ t)
        pure <| graph.foldl (fun acc n _ => if used.contains n then acc else acc.insert n) NameSet.empty
      | none => pure NameSet.empty
    let includeLean := args.hasFlag "include-lean"
    let includeStd := args.hasFlag "include-std" || includeLean
    let includeDeps := args.hasFlag "include-deps" || includeStd
    -- Note: `includeDirect` does not imply `includeDeps`!
    -- e.g. if the package contains `import Lean`, the node `Lean` will be included with
    -- `--include-direct`, but not included with `--include-deps`.
    let includeDirect := args.hasFlag "include-direct"

    -- Helper to get the module that defines a constant (for constant-level graphs)
    let getDefiningModule (n : Name) : Name :=
      match env.getModuleIdxFor? n with
      | some idx => env.header.moduleNames[idx.toNat]!
      | none => n -- fallback: constant not in imported modules, use name as-is

    -- Helper to check if a name belongs to the target package
    -- For module-level graphs: check if name has toModule as prefix
    -- For constant-level graphs: look up defining module, check if IT has toModule as prefix
    let belongsToPackage (n : Name) : Bool :=
      if isConstantLevel then
        let defModule := getDefiningModule n
        toModule.isPrefixOf defModule
      else
        toModule.isPrefixOf n

    -- Fast path: skip expensive operations when includeLean is true and we're in constant-level mode
    -- (proof-deps/type-deps), since --include-lean means "include everything"
    let skipExpensiveFiltering := includeLean && isConstantLevel
    
    -- `directDeps` contains files which are not in the package
    -- but directly imported by a file in the package
    let directDeps : NameSet := if skipExpensiveFiltering then .empty else 
      graph.foldl (init := .empty) (fun acc n deps =>
        if belongsToPackage n then
          deps.filter (!belongsToPackage ·) |>.foldl (init := acc) NameSet.insert
        else
          acc)
    
    let filter (n : Name) : Bool :=
      belongsToPackage n ||
      bif isPrefixOf `Std n then includeStd else
      bif isPrefixOf `Lean n || isPrefixOf `Init n then includeLean else
      includeDeps
    let filterDirect (n : Name) : Bool :=
      includeDirect ∧ directDeps.contains n

    -- Skip expensive filterMap when in fast path
    if !skipExpensiveFiltering then
      graph := graph.filterMap (fun n i =>
        if filter n then
          -- include node regularly
          (i.filter (fun m => filterDirect m || filter m))
        else if filterDirect n then
          -- include node as direct dependency; drop any further deps.
          some #[]
        else
          -- not included
          none)
    if args.hasFlag "exclude-meta" && !skipExpensiveFiltering then
      -- Mathlib-specific exclusion of tactics
      let filterMathlibMeta : Name → Bool := fun n => (
        isPrefixOf `Mathlib.Tactic n ∨
        isPrefixOf `Mathlib.Lean n ∨
        isPrefixOf `Mathlib.Mathport n ∨
        isPrefixOf `Mathlib.Util n)
      graph := graph.filterGraph filterMathlibMeta (replacement := `«Mathlib.Tactics»)

    let markedPackage : Option Name := if args.hasFlag "mark-package" then toModule else none

    -- Write DOT files directly to avoid building massive strings in memory
    -- This must be done inside withImportModules while we have access to the graph data
    if extensions.contains "dot" then
      let dotOutputs := match args.variableArgsAs! String with
        | #[] => #["import_graph.dot"]
        | outputs => outputs.filter (fun o =>
            match (o : FilePath).extension with
            | none | some "dot" => true
            | _ => false)
      for output in dotOutputs do
        IO.FS.withFile output .write fun handle =>
          writeDotGraph handle graph (unused := unused) (markedPackage := markedPackage)
            (directDeps := directDeps)
            (withSorry := modulesWithSorry)
            (to := NameSet.ofArray to) (from_ := NameSet.ofArray (from?.getD #[]))

    -- Create GEXF output (needed for HTML embedding, must be returned as string)
    let mut outFiles : Std.HashMap String String := {}
    if extensions.contains "gexf" then
      let graph₂ := match args.flag? "to" with
        | none => graph.filter (fun n _ => ! if to.contains `Mathlib then #[`Mathlib, `Mathlib.Tactic].contains n else to.contains n)
        | some _ => graph
      let gexfFile := Graph.toGexf graph₂ toModule env
      outFiles := outFiles.insert "gexf" gexfFile
    
    return outFiles

  catch err =>
    -- TODO: try to build `to` first, so this doesn't happen
    throw <| IO.userError <| s!"{err}\nIf the error above says `object file ... does not exist`, " ++
      s!"try if `lake build {" ".intercalate (to.toList.map Name.toString)}` fixes the issue"
    throw err

  -- DOT files have already been written inside withImportModules
  -- Here we only handle GEXF, HTML, and other formats (png, svg, etc.)
  match args.variableArgsAs! String with
  | #[] => pure ()  -- DOT file already written
  | outputs => for o in outputs do
     let fp : FilePath := o
     match fp.extension with
     | none | "dot" => pure ()  -- DOT files already written
     | "gexf" => IO.FS.writeFile fp (outFiles["gexf"]!)
     | "html" =>
        let gexfFile := (outFiles["gexf"]!)
        -- use `html-template/index.html` and insert any dependencies to make it
        -- a stand-alone HTML file.
        -- note: changes in `index.html` might need to be reflected here!
        let exeDir := (FilePath.parent (← IO.appPath) |>.get!) / ".." / ".." / ".."
        let mut html ← IO.FS.readFile <| ← IO.FS.realPath ( exeDir / "html-template" / "index.html")
        for dep in (#[
            "vendor" / "sigma.min.js",
            "vendor" / "graphology.min.js",
            "vendor" / "graphology-library.min.js" ] : Array FilePath) do
          let depContent ← IO.FS.readFile <| ← IO.FS.realPath (exeDir / "html-template" / dep)
          html := html.replace s!"<script src=\"{dep}\"></script>" s!"<script>{depContent}</script>"
        -- inline the graph data
        -- note: changes in `index.html` might need to be reflected here!
        let escapedFile := gexfFile.replace "\n" "" |>.replace "\"" "\\\""
        let toFormatted : String := ", ".intercalate <| (to.map toString).toList
        html := html
          |>.replace "fetch(\"imports.gexf\").then((res) => res.text()).then(render_gexf)" s!"render_gexf(\"{escapedFile}\")"
          |>.replace "<h1>Import Graph</h1>" s!"<h1>Import Graph for {toFormatted}</h1>"
          |>.replace "<title>import graph</title>" s!"<title>import graph for {toFormatted}</title>"
        IO.FS.writeFile fp html
     | some ext => try
        -- For other formats (png, svg, etc.), we need to pipe through graphviz
        -- Read the DOT file that was already written and pipe it to graphviz
        -- Find the corresponding .dot file
        let dotPath := fp.withExtension "dot"
        let dotContent ← IO.FS.readFile dotPath
        _ ← IO.Process.output { cmd := "dot", args := #["-T" ++ ext, "-o", o] } dotContent
      catch ex =>
        IO.eprintln s!"Error occurred while writing out {fp}."
        IO.eprintln s!"Make sure you have `graphviz` installed and the file is writable."
        throw ex
  return 0

/-- Setting up command line options and help text for `lake exe graph`. -/
def graph : Cmd := `[Cli|
  graph VIA importGraphCLI; ["0.0.3"]
  "Generate representations of a Lean import graph. \
   By default generates the import graph up to `Mathlib`. \
   If you are working in a downstream project, use `lake exe graph --to MyProject`."

  FLAGS:
    "mode" : String;           "Graph mode: 'imports' (default), 'hierarchy'/'structures', 'unified'."
    "edge-types" : String;     "For unified mode: comma-separated edge types to include. Valid: extends,field,sig,proof,def,docref. Default: all."
    "include-aux";             "Include all declarations (exhaustive mode, bypasses doc-aligned filter)."
    "to" : Array ModuleName;   "Only show the upstream imports of the specified modules."
    "from" : Array ModuleName; "Only show the downstream dependencies of the specified modules."
    "exclude-meta";            "Exclude any files starting with `Mathlib.[Tactic|Lean|Util|Mathport]`."
    "include-direct";          "Include directly imported files from other libraries"
    "include-deps";            "Include used files from other libraries (not including Lean itself and `std`)"
    "include-std";             "Include used files from the Lean standard library (implies `--include-deps`)"
    "include-lean";            "Include used files from Lean itself (implies `--include-deps` and `--include-std`)"
    "mark-package";            "Visually highlight the package containing the first `--to` target (used in combination with some `--include-XXX`)."
    "mark-sorry";              "Visually highlight modules containing sorries."

  ARGS:
    ...outputs : String;  "Filename(s) for the output. \
      If none are specified, generates `import_graph.dot`. \
      Automatically chooses the format based on the file extension. \
      Currently supported formats are `.dot`, `.gexf`, `.html`, \
      and if you have `graphviz` installed then any supported output format is allowed."
]


/-- `lake exe graph` -/
public def main (args : List String) : IO UInt32 :=
  graph.validate args
