"""P4: batched Lean+Mathlib typecheck of formalized statements.

Given a list of statement TYPES (the part after the colon), write ONE file with
a single `import Mathlib` and each as `theorem tc_<i> : <type> := sorry` on its
own line, then elaborate with `lake env lean` in a built Mathlib project. One
import amortizes over the whole batch. A statement "typechecks" iff its line
produces no `error:` (a `sorry` warning is fine).

This module exposes `typecheck(types: list[str]) -> list[bool]` and a CLI for a
self-test.

    python scripts/run_typecheck.py --selftest
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

MATHLIB_PROJ = Path(os.environ.get("LPR_MATHLIB_DIR", "/home/aurasl/projects/lean-repos/mathlib4"))  # v4.29.0, built


def _wrap(i: int, raw: str) -> str:
    """Normalize a model output into `theorem tc_<i> ... := sorry` on one line.
    Accepts a full declaration (theorem/lemma/def/example + binders + : type),
    a bare `: type`, or a bare type expression; preserves binders."""
    s = " ".join(raw.strip().split())
    s = s.split(":=")[0].strip()                       # drop any proof body
    m = re.match(r"^(?:theorem|lemma|def)\s+\S+\s*(.*)$", s)
    if m:
        rest = m.group(1)                               # binders + : type
    elif s.startswith("example"):
        rest = s[len("example"):].strip()
    elif s.startswith(":"):
        rest = s
    else:
        rest = f": {s}" if s else ": True"
    if ":" not in rest:
        rest = f"{rest} : True" if rest else ": True"   # no type -> guaranteed junk
    return f"theorem tc_{i} {rest} := sorry"


def typecheck(types: list[str], timeout: int = 1800) -> list[bool]:
    """Return per-statement well-formedness. Each entry may be a full Lean
    declaration or a bare type; each is wrapped to tc_<i> on one line."""
    # autoImplicit must be OFF or unknown identifiers in a type silently become
    # implicit binders instead of erroring (Mathlib disables it project-wide).
    lines = ["import Mathlib",
             "set_option autoImplicit false",
             "set_option relaxedAutoImplicit false", ""]
    stmt_line = {}  # statement index -> 1-based file line
    for i, t in enumerate(types):
        lines.append(_wrap(i, t))
        stmt_line[i] = len(lines)               # this statement's line number
    src = "\n".join(lines) + "\n"

    with tempfile.NamedTemporaryFile("w", suffix=".lean", dir="/tmp",
                                     delete=False) as f:
        f.write(src); path = f.name

    proc = subprocess.run(["lake", "env", "lean", path], cwd=MATHLIB_PROJ,
                          capture_output=True, text=True, timeout=timeout)
    out = proc.stdout + proc.stderr

    # lines carrying a real error (sorry is a warning, not an error)
    # Lean reports `error:` or `error(lean.someKind):` — match both.
    bad_lines = set()
    for m in re.finditer(rf"{re.escape(path)}:(\d+):\d+: error(?:\([^)]*\))?:", out):
        bad_lines.add(int(m.group(1)))
    ok = [stmt_line[i] not in bad_lines for i in range(len(types))]
    return ok


def _selftest():
    cases = [
        ("(n : Nat) -> n + 0 = n", True),                 # valid
        ("Continuous (fun x : Real => x + 1)", True),     # valid
        ("Nonexistent.lemma 3 = froobar", False),         # unknown identifiers
        ('(2 : Nat) = "two"', False),                     # type error (Nat = String)
    ]
    res = typecheck([c[0] for c in cases])
    allok = True
    for (t, exp), got in zip(cases, res):
        flag = "ok" if got == exp else "MISMATCH"
        if got != exp: allok = False
        print(f"  [{flag}] expected={exp} got={got}  {t}")
    print("SELFTEST", "PASS" if allok else "FAIL")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
