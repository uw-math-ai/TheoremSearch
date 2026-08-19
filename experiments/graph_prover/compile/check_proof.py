"""Whole-proof checker: one candidate proof -> CompileResult (proof-level reward only).

Extends the statement-typecheck pattern of
experiments/lean_premise_retrieval/scripts/run_typecheck.py to complete proofs.
One candidate per file — a broken proof (unterminated `by` block) can poison every
later declaration, so proofs are never batched.

The wrapper file (proof_check_template.lean) adds two probes after the declaration:
  #print axioms cand      -> the sorry/axiom gate (AXIOMS_RE pattern shared with
                             autoformalizing-benchmarks/formalization-workflow/scripts/check_node.py)
  run_cmd USED_CONSTANTS  -> kernel-level list of constants the proof term uses.
                             This is (a) the self-citation gate — a proof that cites the
                             masked target or anything in its forbidden set is rejected,
                             which string matching cannot guarantee (exact?/apply? find
                             names the model never typed) — and (b) free premise-usage
                             provenance.

If the run_cmd metaprogram fails on the pinned toolchain (API drift), we degrade to
whole-identifier string matching on the proof body and mark
used_constants_source="string-match" so score.py can report the weaker gate.

Selftest (needs LPR_MATHLIB_DIR pointing at a built `import Mathlib` project):
    python -m experiments.graph_prover.compile.check_proof --selftest
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from ..provenance import CompileResult

MATHLIB_PROJ = None  # resolved lazily from config so import stays env-free
TEMPLATE = (Path(__file__).parent / "proof_check_template.lean").read_text()

PERMITTED_AXIOMS = {"propext", "Quot.sound", "Classical.choice"}

# Same shape as autoformalizing-benchmarks .../check_node.py:24
AXIOMS_RE = re.compile(r"'([^']+)' depends on axioms: \[([^\]]*)\]")
NO_AXIOMS_RE = re.compile(r"'([^']+)' does not depend on any axioms")
ERROR_RE_TMPL = r"{path}:(\d+):(\d+): error(?:\([^)]*\))?: ?(.*)"
USED_RE = re.compile(r"USED_CONSTANTS: \[([^\]]*)\]")

IDENT_CHARS = r"[A-Za-z0-9_'.₀-₉¡-￿]"


def _mathlib_proj() -> Path:
    global MATHLIB_PROJ
    if MATHLIB_PROJ is None:
        from .. import config
        if not config.MATHLIB_DIR:
            raise RuntimeError("LPR_MATHLIB_DIR not set — compile stages need a built "
                               "`import Mathlib` project")
        MATHLIB_PROJ = Path(config.MATHLIB_DIR)
    return MATHLIB_PROJ


def string_match_constants(proof_text: str, names: set[str]) -> list[str]:
    """Weaker fallback: whole-identifier match of decl names in the proof body.
    Same idea as lean_premise_retrieval/scripts/score_formalization.py::prem_recall."""
    hits = []
    for n in names:
        if re.search(rf"(?<!{IDENT_CHARS}){re.escape(n)}(?!{IDENT_CHARS})", proof_text):
            hits.append(n)
    return hits


def check_proof(declaration: str,
                forbidden_names: set[str] | None = None,
                offered_names: set[str] | None = None,
                timeout: int = 600) -> CompileResult:
    """Compile `declaration` (a full `theorem cand ... := ...`) against Mathlib.

    forbidden_names: decl names whose use invalidates the proof (target + reverse deps).
    offered_names: for the string-match fallback universe (kernel path needs no help).
    """
    forbidden_names = forbidden_names or set()
    src = TEMPLATE.replace("{DECLARATION}", declaration.strip())
    t0 = time.time()
    with tempfile.NamedTemporaryFile("w", suffix=".lean", dir="/tmp", delete=False) as f:
        f.write(src)
        path = f.name

    try:
        proc = subprocess.run(["lake", "env", "lean", path], cwd=_mathlib_proj(),
                              capture_output=True, text=True, timeout=timeout)
        out = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired as e:
        out = ((e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")) \
            + "\nCHECK_TIMEOUT"
        return CompileResult(compiles=False, sorry_free=False,
                             errors=[{"line": 0, "col": 0, "message": "timeout"}],
                             wall_time_s=time.time() - t0, raw_tail=out[-2000:])

    errors = [{"line": int(m.group(1)), "col": int(m.group(2)),
               "message": m.group(3).strip()}
              for m in re.finditer(ERROR_RE_TMPL.format(path=re.escape(path)), out)]
    compiles = not errors

    axioms: list[str] = []
    sorry_free = False
    m = AXIOMS_RE.search(out)
    if m and m.group(1) == "cand":
        axioms = [a.strip() for a in m.group(2).split(",") if a.strip()]
        sorry_free = compiles and "sorryAx" not in axioms and \
            all(a in PERMITTED_AXIOMS for a in axioms)
    elif NO_AXIOMS_RE.search(out):
        axioms = []
        sorry_free = compiles

    used: list[str] = []
    used_src = "none"
    mu = USED_RE.search(out)
    if mu is not None:
        used = [u.strip() for u in mu.group(1).split(",") if u.strip()]
        used_src = "kernel"
    elif compiles:
        # run_cmd probe didn't produce output — degrade to string matching over the
        # names we know about (forbidden + offered).
        universe = set(forbidden_names) | set(offered_names or ())
        used = string_match_constants(declaration, universe)
        used_src = "string-match"

    forbidden_used = sorted(set(used) & forbidden_names)

    return CompileResult(compiles=compiles, sorry_free=sorry_free, axioms=axioms,
                         used_constants=used, used_constants_source=used_src,
                         errors=errors, forbidden_used=forbidden_used,
                         wall_time_s=time.time() - t0, raw_tail=out[-2000:])


def _selftest():
    """5 cases per the approved plan: valid / sorry / wrong / forbidden-citing / unknown-id."""
    cases = [
        ("valid proof",
         "theorem cand (n : Nat) : n + 0 = n := Nat.add_zero n",
         set(), lambda r: r.compiles and r.sorry_free and r.solved),
        ("sorry proof",
         "theorem cand (n : Nat) : n + 0 = n := sorry",
         set(), lambda r: r.compiles and not r.sorry_free),
        ("wrong proof",
         "theorem cand (n : Nat) : n + 0 = n := Nat.zero_add n",
         set(), lambda r: not r.compiles),
        ("forbidden-citing proof (self-citation gate)",
         "theorem cand (n : Nat) : n + 0 = n := Nat.add_zero n",
         {"Nat.add_zero"}, lambda r: r.compiles and not r.solved and r.forbidden_used),
        ("unknown identifier",
         "theorem cand (n : Nat) : n + 0 = n := Froobar.nonexistent n",
         set(), lambda r: not r.compiles and any(
             "unknown" in e["message"].lower() for e in r.errors)),
    ]
    allok = True
    for name, decl, forbidden, check in cases:
        r = check_proof(decl, forbidden_names=forbidden)
        ok = check(r)
        allok &= ok
        print(f"  [{'ok' if ok else 'MISMATCH'}] {name}: compiles={r.compiles} "
              f"sorry_free={r.sorry_free} solved={r.solved} used_src={r.used_constants_source} "
              f"forbidden_used={r.forbidden_used}")
        if r.used_constants_source == "none" and r.compiles:
            print("      WARNING: used-constants probe produced nothing on a compiling "
                  "proof — check run_cmd availability on this toolchain")
    print("SELFTEST", "PASS" if allok else "FAIL")
    return allok


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if _selftest() else 1)
