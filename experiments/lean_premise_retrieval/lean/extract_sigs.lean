import Mathlib
import Lean
open Lean Lean.Elab.Command Lean.PrettyPrinter

/-- Pretty-print the signature of every v4.29 Mathlib decl (names read from
`/tmp/ml429_names.txt`), as `name<TAB>sig` lines. Serves as both the RAG-context
sig source and the library-search listing for the large-corpus experiment. -/
run_cmd do
  let env ← getEnv
  let oldTxt ← IO.FS.readFile "/tmp/ml429_names.txt"
  let mut want : Std.HashSet Name := {}
  for line in oldTxt.splitOn "\n" do
    let l := line.trim
    if !l.isEmpty then want := want.insert l.toName
  let esc := fun (s : String) => s.replace "\t" " " |>.replace "\n" " "
  let mut h ← IO.FS.Handle.mk "/tmp/ml429_namesigs.tsv" IO.FS.Mode.write
  let mut n := 0
  for (name, ci) in env.constants.toList do
    if name.isInternal then continue
    unless want.contains name do continue
    let sig ← (do
      try
        let fmt ← liftCoreM <| Meta.MetaM.run' (Meta.ppExpr ci.type)
        pure (toString fmt)
      catch _ => pure "")
    if sig.isEmpty then continue
    h.putStrLn (toString name ++ "\t" ++ esc sig)
    n := n + 1
    if n % 20000 == 0 then IO.eprintln s!"  pp {n}"
  IO.eprintln s!"wrote {n} name+sig lines"
