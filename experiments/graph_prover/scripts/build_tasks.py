"""Task mining: held-out Mathlib theorems -> masked proof-reconstruction tasks.

Reuses the frozen module-held-out split from lean_premise_retrieval
(cache/split.json: val for development, test for the frozen run). For each candidate:

  - statement body + kind (theorem/lemma only) + decl_name from RDS v2
  - gold labels = formal_dependency rows with edge_type='proof' (the PROOF deps,
    not build_split's sig/extends/field statement-level deps); keep 2..15
  - the statement is masked (proof stripped, decl renamed `cand`, `:= sorry`)
  - mining gate: every masked statement must typecheck with sorry
    (lean_premise_retrieval/scripts/run_typecheck.py, batched)
  - stratified sample (by module prefix) N=150 val / 200 test, SEED=42

Output: cache/tasks_<split>_pre.json — build_forbidden.py then adds the forbidden
sets and writes cache/tasks_<split>.json.

Masking selftest (pure string, no DB/Lean):
    python -m experiments.graph_prover.scripts.build_tasks --selftest
"""
from __future__ import annotations

import argparse
import json
import pickle
import random
import re
import sys

from .. import config

DECL_RE = re.compile(r"\b(theorem|lemma)\s+([A-Za-z0-9_'.₀-₉«»¡-￿]+)")

_OPEN = {"(": ")", "[": "]", "{": "}", "⟨": "⟩", "⦃": "⦄", "⁅": "⁆"}
_CLOSE = set(_OPEN.values())


def split_proof(body: str) -> tuple[str, str] | None:
    """Split a declaration at the first top-level `:=` (outside brackets, comments,
    strings). Returns (header, proof) or None if no top-level `:=` found."""
    depth = 0
    i, n = 0, len(body)
    while i < n:
        ch = body[i]
        two = body[i:i + 2]
        if two == "--":                       # line comment
            j = body.find("\n", i)
            i = n if j == -1 else j + 1
            continue
        if two == "/-":                       # block comment (nested)
            lvl, i = 1, i + 2
            while i < n and lvl:
                if body[i:i + 2] == "/-":
                    lvl += 1; i += 2
                elif body[i:i + 2] == "-/":
                    lvl -= 1; i += 2
                else:
                    i += 1
            continue
        if ch == '"':                         # string literal
            i += 1
            while i < n and body[i] != '"':
                i += 2 if body[i] == "\\" else 1
            i += 1
            continue
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth -= 1
        elif depth == 0 and two == ":=":
            return body[:i].rstrip(), body[i + 2:].strip()
        i += 1
    return None


def mask_statement(body: str) -> str | None:
    """theorem/lemma declaration -> `theorem cand <binders> : <type> := sorry`.
    Strips leading attributes/modifiers; returns None if unparseable."""
    s = body.strip()
    # strip leading attributes  @[...]  (bracket-aware) and modifiers
    while True:
        s = s.lstrip()
        if s.startswith("@["):
            depth, j = 0, 1
            while j < len(s):
                if s[j] == "[":
                    depth += 1
                elif s[j] == "]":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            s = s[j + 1:]
            continue
        m = re.match(r"^(private|protected|nonrec|noncomputable|scoped)\s+", s)
        if m:
            s = s[m.end():]
            continue
        break
    m = DECL_RE.match(s)
    if not m:
        return None
    split = split_proof(s)
    header = split[0] if split else s.rstrip()
    header = DECL_RE.sub("theorem cand", header, count=1)
    if ":" not in header[len("theorem cand"):]:
        return None
    return f"{header} := sorry"


TASK_SQL = """
SELECT st.statement_id::text, st.kind, st.body, fm.decl_name, fm.module
FROM statement st
JOIN formal_metadata fm ON fm.statement_id = st.statement_id
WHERE st.statement_id = ANY(%(tids)s::uuid[])
  AND st.kind IN ('theorem', 'lemma')
"""

PROOF_DEPS_SQL = """
SELECT fd.src_id::text, fd.dep_id::text, fm.decl_name
FROM formal_dependency fd
LEFT JOIN formal_metadata fm ON fm.statement_id = fd.dep_id
WHERE fd.src_id = ANY(%(tids)s::uuid[])
  AND fd.edge_type = 'proof'
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["val", "test"], default="val")
    ap.add_argument("--n", type=int, default=None, help="default: 150 val / 200 test")
    ap.add_argument("--min-deps", type=int, default=2)
    ap.add_argument("--max-deps", type=int, default=15)
    ap.add_argument("--max-proof-lines", type=int, default=15)
    ap.add_argument("--skip-typecheck-gate", action="store_true")
    args = ap.parse_args()
    n_target = args.n or (150 if args.split == "val" else 200)

    split = json.loads((config.LPR_CACHE / "split.json").read_text())
    tids = list(split[args.split])
    print(f"[split] {args.split}: {len(tids)} candidate targets")

    conn = config.get_rds_conn()
    rows = {}
    with conn.cursor() as cur:
        for s in range(0, len(tids), 5000):
            cur.execute(TASK_SQL, {"tids": tids[s:s + 5000]})
            for sid, kind, body, decl, module in cur.fetchall():
                rows[sid] = {"kind": kind, "body": body or "",
                             "decl_name": decl, "module": module or ""}
    print(f"[db] {len(rows)} theorem/lemma bodies")

    deps: dict[str, list[tuple[str, str]]] = {}
    with conn.cursor() as cur:
        keys = list(rows)
        for s in range(0, len(keys), 5000):
            cur.execute(PROOF_DEPS_SQL, {"tids": keys[s:s + 5000]})
            for src, dep, dep_name in cur.fetchall():
                deps.setdefault(src, []).append((dep, dep_name or ""))

    slogans = {}
    sp = config.LPR_CACHE / "slogans.pkl"
    if sp.exists():
        slogans = pickle.load(open(sp, "rb"))

    namesig_names = set()
    nspath = config.LPR_CACHE / "ml429_namesigs.tsv"
    if nspath.exists():
        namesig_names = {l.partition("\t")[0] for l in nspath.read_text().splitlines()}

    tasks = []
    stats = {"no_deps": 0, "dep_range": 0, "mask_fail": 0, "not_in_listing": 0,
             "proof_len": 0}
    for tid, r in rows.items():
        d = deps.get(tid, [])
        if not d:
            stats["no_deps"] += 1
            continue
        if not (args.min_deps <= len(d) <= args.max_deps):
            stats["dep_range"] += 1
            continue
        if namesig_names and r["decl_name"] not in namesig_names:
            stats["not_in_listing"] += 1
            continue
        masked = mask_statement(r["body"])
        if masked is None:
            stats["mask_fail"] += 1
            continue
        split_pf = split_proof(r["body"].strip())
        if split_pf is not None:
            if split_pf[1].count("\n") + 1 > args.max_proof_lines:
                stats["proof_len"] += 1
                continue
        tasks.append({
            "tid": tid, "decl_name": r["decl_name"], "module": r["module"],
            "statement_masked": masked,
            "gold_proof_deps": [dep for dep, _ in d],
            "gold_proof_dep_names": [nm for _, nm in d if nm],
            "slogan": slogans.get(tid, ""),
        })
    print(f"[filter] kept {len(tasks)}; dropped {stats}")

    # mining gate: masked statements must typecheck with sorry (batched)
    if not args.skip_typecheck_gate:
        tc = config.load_run_typecheck()
        ok = tc.typecheck([t["statement_masked"] for t in tasks])
        tasks = [t for t, o in zip(tasks, ok) if o]
        print(f"[typecheck-gate] {sum(ok)}/{len(ok)} masked statements typecheck")

    # stratified sample by top-level module prefix
    rng = random.Random(config.SEED)
    by_prefix: dict[str, list] = {}
    for t in tasks:
        by_prefix.setdefault(t["module"].split(".")[1] if "." in t["module"] else "?",
                             []).append(t)
    sample = []
    prefixes = sorted(by_prefix)
    while len(sample) < min(n_target, len(tasks)):
        for p in prefixes:
            if by_prefix[p] and len(sample) < n_target:
                sample.append(by_prefix[p].pop(rng.randrange(len(by_prefix[p]))))
    out = config.CACHE_DIR / f"tasks_{args.split}_pre.json"
    out.write_text(json.dumps(sample, indent=1))
    print(f"[out] {len(sample)} tasks -> {out}\n"
          "next: python -m experiments.graph_prover.scripts.build_forbidden "
          f"--split {args.split}")


def _selftest():
    cases = [
        ("theorem foo (n : Nat) : n + 0 = n := by simp",
         "theorem cand (n : Nat) : n + 0 = n := sorry"),
        ("@[simp]\ntheorem bar {α : Type} (l : List α) : l ++ [] = l :=\n  List.append_nil l",
         "theorem cand {α : Type} (l : List α) : l ++ [] = l := sorry"),
        # := inside binder default value must NOT split there... Lean uses := in
        # structure instances within the type; bracket-guarded:
        ("lemma baz (h : ∀ x ∈ ({a := 1} : Foo), x = x) : True := trivial",
         "theorem cand (h : ∀ x ∈ ({a := 1} : Foo), x = x) : True := sorry"),
        ("protected theorem Nat.qux : 1 = 1 := rfl",
         "theorem cand : 1 = 1 := sorry"),
        ("def notATheorem : Nat := 3", None),
        ("theorem no_type_colon := rfl", None),
        ("theorem comment_trap -- := fake\n  : 2 = 2 := rfl",
         "theorem cand -- := fake\n  : 2 = 2 := sorry"),
    ]
    allok = True
    for body, want in cases:
        got = mask_statement(body)
        ok = got == want
        allok &= ok
        print(f"  [{'ok' if ok else 'MISMATCH'}] {body[:50]!r}\n"
              f"      -> {got!r}" + ("" if ok else f"\n      want {want!r}"))
    print("SELFTEST", "PASS" if allok else "FAIL")
    return allok


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if _selftest() else 1)
    main()
