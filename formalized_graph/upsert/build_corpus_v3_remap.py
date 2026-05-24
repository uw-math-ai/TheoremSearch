"""Compute a per-node remap from corpus_v3's current (wrong) project_id to the
correct one, using module prefixes + per-version ndjson membership.

Background: corpus_v3.db's ingest happened in alphabetical order under
`INSERT OR IGNORE ON nodes.full_name UNIQUE`, so each shared declaration was
claimed by whichever project's ndjson reached it first. That made e.g.
ClassFieldTheory "own" 162k Mathlib decls. RDS picked up the same wrong
attribution via `upsert_formal_statements.py:135` (which reads
`nodes.project_id` → `projects.name` → `paper.external_id`).

This script computes the *correct* attribution without re-ingesting the SQLite
DB. It uses two signals:

1. **Module prefix** — the first dot-segment of `nodes.module` (e.g.
   `Mathlib.Analysis.Normed` → `Mathlib`). For each prefix we know the
   library it belongs to via a hand-built table (see PREFIX_TO_PROJECT).

2. **Multi-version disambiguation via per-ndjson set membership** — for
   `Mathlib.*` / `Batteries.*` / `Std.*` (which span v427/v428/v429), we read
   the three per-toolchain ndjsons and pick the earliest version that
   contains each decl_name. Same idea for `SpherePacking.*`, which is shared
   by `Sphere-Packing-Lean` and `sphere-packing-math-inc`.

The output is a TSV with one row per current node:

    full_name <TAB> current_project <TAB> new_project <TAB> source_rule

`source_rule` records which signal drove the assignment ("prefix-clean",
"multi-version: v428", "ambiguous: math-inc", "lean-core→Mathlib_v427",
etc.) so the result is fully auditable.

NOTE — this script does NOT touch RDS and does NOT modify corpus_v3.db.
It only reads, then writes a TSV + a summary JSON next to it.

Usage:
  python3.12 formalized_graph/upsert/build_corpus_v3_remap.py
  python3.12 formalized_graph/upsert/build_corpus_v3_remap.py --db /path/to/corpus_v3.db --out remap.tsv
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

# ---------------------------------------------------------------- prefix table

# Hand-built mapping: module first-segment → either a single project name
# (the canonical case) or a marker that triggers per-decl multi-version /
# ambiguous logic in resolve_target().
#
# Verified against `SELECT prefix, COUNT(*) FROM nodes GROUP BY prefix` on
# the existing /gscratch/amath/aurasoph/lean-graph-corpus-v3/corpus_v3.db.
# Unknown prefixes (LeanCert / PrimeCert / Architect) were tracked back to
# their ndjson via grep and confirmed as PrimeNumberTheoremAnd subdirs.

MARKER_MULTI_MATHLIB = "__MULTI_MATHLIB__"
MARKER_MULTI_BATTERIES = "__MULTI_BATTERIES__"
MARKER_SPHERE_PACKING = "__SPHERE_PACKING__"
# Lean stdlib + ecosystem deps that ride along with Mathlib. Decls under these
# prefixes get attributed to whichever Mathlib version first transitively
# imports them — same first-introduced semantics as Mathlib.* itself.
MARKER_LEAN_VIA_MATHLIB = "__LEAN_VIA_MATHLIB__"

PREFIX_TO_PROJECT: dict[str, str] = {
    # Multi-version: per-decl resolution via ndjson membership
    "Mathlib":               MARKER_MULTI_MATHLIB,
    "Std":                   MARKER_MULTI_BATTERIES,
    "Batteries":             MARKER_MULTI_BATTERIES,
    # Ambiguous: two projects share this namespace
    "SpherePacking":         MARKER_SPHERE_PACKING,
    # Lean core / build tooling and Mathlib ecosystem deps. Attributed to
    # whichever Mathlib version first transitively imports them (so e.g. an
    # Init.Data.Iterators.* decl introduced in Lean 4.28 lands under
    # Mathlib_v428, not Mathlib_v427).
    "Init":                  MARKER_LEAN_VIA_MATHLIB,
    "Lean":                  MARKER_LEAN_VIA_MATHLIB,
    "Lake":                  MARKER_LEAN_VIA_MATHLIB,
    "Aesop":                 MARKER_LEAN_VIA_MATHLIB,
    "Qq":                    MARKER_LEAN_VIA_MATHLIB,
    "Plausible":             MARKER_LEAN_VIA_MATHLIB,
    "ProofWidgets":          MARKER_LEAN_VIA_MATHLIB,
    "LeanSearchClient":      MARKER_LEAN_VIA_MATHLIB,
    "KolmogorovExtension4":  MARKER_LEAN_VIA_MATHLIB,
    "ImportGraph":           MARKER_LEAN_VIA_MATHLIB,
    # Carleson and certain other projects vendored sub-libraries that show
    # up only in their ndjson — keep them under the parent project.
    "LeanCert":              "PrimeNumberTheoremAnd",
    "PrimeCert":             "PrimeNumberTheoremAnd",
    "Architect":             "PrimeNumberTheoremAnd",
    # Community projects — each owns its own namespace
    "Physlib":               "physlib",
    "Carleson":              "carleson",
    "CombinatorialGames":    "combinatorial-games",
    "PrimeNumberTheoremAnd": "PrimeNumberTheoremAnd",
    "FLT":                   "FLT",
    "Cslib":                 "cslib",
    "ClassFieldTheory":      "ClassFieldTheory",
    "SphereEversion":        "sphere-eversion",
    "PFR":                   "pfr",
    "BrownianMotion":        "brownian-motion",
    "APAP":                  "apap",
    "FormalConjecturesForMathlib": "formal-conjectures",
    "Toric":                 "toric",
    "FltRegular":            "flt-regular",
    "MiscYD":                "misc-yd",
    "HarderNarasimhan":      "HarderNarasimhan",
    "AddCombi":              "add-combi",
    "PersistentDecomp":      "PersistentDecomp",
    "LeanCamCombi":          "cam-combi",   # uncertain — verify via summary
    "GibbsMeasure":          "gibbs-measure",
    "ForbiddenMatrix":       "forbidden-matrix",
    "ChandraFurstLipton":    "chandra-furst-lipton",
}

# Per-user policy for SpherePacking ambiguity:
SPHERE_PACKING_OVERLAP_DEFAULT = "Sphere-Packing-Lean"
SPHERE_PACKING_PROJECTS = ("Sphere-Packing-Lean", "sphere-packing-math-inc")

# ---------------------------------------------------------------- ndjson loaders


def load_decl_names(ndjson_path: Path, module_prefix: str | None = None) -> set[str]:
    """Stream a single .ndjson and collect decl `name` values.

    If `module_prefix` is set (e.g. "Mathlib"), filter to decls whose module
    starts with that prefix (or equals it exactly) — i.e. ignore the
    transitive-import contamination in that ndjson.
    """
    names: set[str] = set()
    with open(ndjson_path) as f:
        for line in f:
            try:
                o = json.loads(line)
            except Exception:
                continue
            if module_prefix is not None:
                m = o.get("module", "") or ""
                if not (m == module_prefix or m.startswith(module_prefix + ".")):
                    continue
            n = o.get("name")
            if n:
                names.add(n)
    return names


def load_multi_version_sets(
    ndjson_dir: Path,
    project_base: str,
    lib_prefix: tuple[str, ...] | None = None,
) -> dict[str, set[str]]:
    """For Mathlib / Batteries — return {v427: {names}, v428: {names}, v429: {names}}.

    `project_base` is e.g. "Mathlib" or "Batteries"; the ndjsons are named
    `Mathlib_v427.ndjson` etc. `lib_prefix` is the set of module prefixes
    that count as belonging to this library — if `None`, no filter is
    applied (use this to load FULL ndjson decl sets, including transitive
    Init/Std/Aesop etc. — useful for ABSENT_FALLBACK lookups).
    """
    out = {}
    for v in ("v427", "v428", "v429"):
        path = ndjson_dir / f"{project_base}_{v}.ndjson"
        if not path.exists():
            sys.exit(f"missing required ndjson: {path}")
        names: set[str] = set()
        with open(path) as f:
            for line in f:
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if lib_prefix is not None:
                    m = o.get("module", "") or ""
                    if not any(m == p or m.startswith(p + ".") for p in lib_prefix):
                        continue
                n = o.get("name")
                if n:
                    names.add(n)
        out[v] = names
    return out


# ------------------------------------------------------------------ resolution


def first_introduced(
    name: str,
    sets: dict[str, set[str]],
    project_base: str,
    mathlib_full: dict[str, set[str]] | None = None,
) -> tuple[str, str]:
    """Determine which version of a multi-version library first introduced `name`.

    Returns (project_name, source_rule_tag). project_base is "Mathlib" or "Batteries".

    ABSENT_FALLBACK: if the decl has the project_base prefix but isn't in any
    project_base_v* ndjson (e.g. `Std.Data.ExtTreeSet.size` lives in Lean
    4.29 stdlib, not in Batteries), fall back to whichever Mathlib version
    first transitively imported it. `mathlib_full` is the unfiltered Mathlib
    ndjson decl sets (i.e. including Init / Lean / Std / Aesop / ...).
    """
    in7 = name in sets["v427"]
    in8 = name in sets["v428"]
    in9 = name in sets["v429"]
    if in7:
        return f"{project_base}_v427", f"multi-version: 7{'8' if in8 else '-'}{'9' if in9 else '-'}"
    if in8:
        return f"{project_base}_v428", f"multi-version: -8{'9' if in9 else '-'}"
    if in9:
        return f"{project_base}_v429", "multi-version: --9"
    # Not in any per-library ndjson — try the Mathlib ndjsons as a transitive
    # signal so e.g. Std.Data.* from Lean 4.29 stdlib gets attributed to the
    # earliest Mathlib that imports it.
    if mathlib_full is not None:
        m_in7 = name in mathlib_full["v427"]
        m_in8 = name in mathlib_full["v428"]
        m_in9 = name in mathlib_full["v429"]
        if m_in7:
            return "Mathlib_v427", f"ABSENT_FALLBACK ({project_base}.*) → Mathlib_v427 (in Mathlib_v427.ndjson)"
        if m_in8:
            return "Mathlib_v428", f"ABSENT_FALLBACK ({project_base}.*) → Mathlib_v428 (new in v428 ndjson)"
        if m_in9:
            return "Mathlib_v429", f"ABSENT_FALLBACK ({project_base}.*) → Mathlib_v429 (new in v429 ndjson)"
    # True orphan — keep under Mathlib_v427 as the catch-all
    return "Mathlib_v427", f"ABSENT_FALLBACK ({project_base}.*) → Mathlib_v427 (not in any ndjson)"


# -------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path,
                    default=Path("/gscratch/amath/simku22/corpus_v3_fixed/corpus_v3.db"),
                    help="path to corpus_v3.db (the WRONG-attribution one to remap)")
    ap.add_argument("--ndjson-dir", type=Path,
                    default=Path("/gscratch/amath/aurasoph/lean-graph-corpus-v3/ndjson"),
                    help="directory containing the per-project .ndjson files")
    ap.add_argument("--out", type=Path,
                    default=Path("/gscratch/amath/simku22/corpus_v3_fixed/remap.tsv"),
                    help="output TSV path")
    args = ap.parse_args()

    if not args.db.exists():
        sys.exit(f"missing --db: {args.db}")
    if not args.ndjson_dir.exists():
        sys.exit(f"missing --ndjson-dir: {args.ndjson_dir}")

    # 1. Load multi-version sets for Mathlib + Batteries (~few seconds each).
    print(f"loading Mathlib_v{{427,428,429}}.ndjson decl sets...", flush=True)
    mathlib_sets = load_multi_version_sets(args.ndjson_dir, "Mathlib", ("Mathlib",))
    for v, s in mathlib_sets.items():
        print(f"  Mathlib_{v}: {len(s):,} Mathlib.* names")

    print(f"loading Batteries_v{{427,428,429}}.ndjson decl sets...", flush=True)
    batteries_sets = load_multi_version_sets(args.ndjson_dir, "Batteries", ("Batteries", "Std"))
    for v, s in batteries_sets.items():
        print(f"  Batteries_{v}: {len(s):,} Batteries|Std.* names")

    print(f"loading Mathlib_v{{427,428,429}}.ndjson FULL decl sets (for ABSENT_FALLBACK)...", flush=True)
    mathlib_full_sets = load_multi_version_sets(args.ndjson_dir, "Mathlib", lib_prefix=None)
    for v, s in mathlib_full_sets.items():
        print(f"  Mathlib_{v} (full): {len(s):,} names (incl. Init/Std/Aesop/...)")

    # 2. Load SpherePacking-namespace decls from each project's ndjson.
    print("loading SpherePacking.* sets from sphere-packing-* ndjsons...", flush=True)
    sp_sets: dict[str, set[str]] = {}
    for proj in SPHERE_PACKING_PROJECTS:
        # In the ndjson filename, sphere-packing-math-inc / Sphere-Packing-Lean
        # are present verbatim.
        path = args.ndjson_dir / f"{proj}.ndjson"
        sp_sets[proj] = load_decl_names(path, module_prefix="SpherePacking")
        print(f"  {proj}: {len(sp_sets[proj]):,} SpherePacking.* names")

    # 3. Walk nodes in the DB and resolve target per node.
    print(f"\nresolving targets for nodes in {args.db}...", flush=True)
    conn = sqlite3.connect(f"file:{args.db}?mode=ro&immutable=1", uri=True)
    cur = conn.cursor()
    # name → project_name (the WRONG attribution we want to fix)
    project_by_id = dict(cur.execute("SELECT id, name FROM projects").fetchall())

    total = cur.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    print(f"  nodes: {total:,}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    rule_counter: Counter[str] = Counter()
    transition_counter: Counter[tuple[str, str]] = Counter()
    unmapped_examples: list[tuple[str, str]] = []
    unmapped_count = 0
    stays_same = 0
    moves = 0

    with open(args.out, "w") as out_f:
        out_f.write("full_name\tcurrent_project\tnew_project\tsource_rule\tcurrent_module\n")

        chunk_size = 50_000
        cur.execute("SELECT id, project_id, full_name, module FROM nodes")
        while True:
            rows = cur.fetchmany(chunk_size)
            if not rows:
                break
            for node_id, pid, full_name, module in rows:
                current_proj = project_by_id.get(pid, "?")
                # Determine prefix
                module = module or ""
                if "." in module:
                    prefix = module.split(".", 1)[0]
                else:
                    prefix = module

                target = PREFIX_TO_PROJECT.get(prefix)
                rule_tag: str

                if target is None:
                    unmapped_count += 1
                    if len(unmapped_examples) < 20:
                        unmapped_examples.append((prefix, full_name))
                    new_proj = "UNMAPPED"
                    rule_tag = f"unmapped-prefix:{prefix or '(empty)'}"
                elif target == MARKER_MULTI_MATHLIB:
                    new_proj, rule_tag = first_introduced(full_name, mathlib_sets, "Mathlib",
                                                          mathlib_full=mathlib_full_sets)
                elif target == MARKER_MULTI_BATTERIES:
                    new_proj, rule_tag = first_introduced(full_name, batteries_sets, "Batteries",
                                                          mathlib_full=mathlib_full_sets)
                elif target == MARKER_LEAN_VIA_MATHLIB:
                    # Decl with a Lean-ecosystem prefix (Init/Lean/Aesop/...).
                    # Attribute to first Mathlib version that contains it.
                    in_m7 = full_name in mathlib_full_sets["v427"]
                    in_m8 = full_name in mathlib_full_sets["v428"]
                    in_m9 = full_name in mathlib_full_sets["v429"]
                    if in_m7:
                        new_proj = "Mathlib_v427"
                        rule_tag = f"lean-via-mathlib ({prefix}.*): in Mathlib_v427"
                    elif in_m8:
                        new_proj = "Mathlib_v428"
                        rule_tag = f"lean-via-mathlib ({prefix}.*): new in Mathlib_v428"
                    elif in_m9:
                        new_proj = "Mathlib_v429"
                        rule_tag = f"lean-via-mathlib ({prefix}.*): new in Mathlib_v429"
                    else:
                        new_proj = "Mathlib_v427"
                        rule_tag = f"lean-via-mathlib ({prefix}.*): orphan → Mathlib_v427"
                elif target == MARKER_SPHERE_PACKING:
                    in_lean = full_name in sp_sets["Sphere-Packing-Lean"]
                    in_mi   = full_name in sp_sets["sphere-packing-math-inc"]
                    if in_lean and in_mi:
                        new_proj = SPHERE_PACKING_OVERLAP_DEFAULT
                        rule_tag = "sphere-packing: BOTH → overlap-default"
                    elif in_lean:
                        new_proj = "Sphere-Packing-Lean"
                        rule_tag = "sphere-packing: lean-only"
                    elif in_mi:
                        new_proj = "sphere-packing-math-inc"
                        rule_tag = "sphere-packing: math-inc-only"
                    else:
                        # Neither — shouldn't happen for a SpherePacking.* node
                        new_proj = SPHERE_PACKING_OVERLAP_DEFAULT
                        rule_tag = "sphere-packing: ABSENT_FALLBACK"
                else:
                    new_proj = target
                    rule_tag = f"prefix-clean: {prefix}"

                rule_counter[rule_tag] += 1
                transition_counter[(current_proj, new_proj)] += 1
                if new_proj == current_proj:
                    stays_same += 1
                else:
                    moves += 1

                out_f.write(f"{full_name}\t{current_proj}\t{new_proj}\t{rule_tag}\t{module}\n")

    # 4. Summary
    print(f"\nwrote {args.out}  ({args.out.stat().st_size:,} bytes)")
    print(f"\n  total nodes:       {total:,}")
    print(f"  stays under same:  {stays_same:,}")
    print(f"  moves to new:      {moves:,}")
    print(f"  unmapped:          {unmapped_count:,}")

    summary = {
        "total_nodes": total,
        "stays_same": stays_same,
        "moves": moves,
        "unmapped": unmapped_count,
        "rules": dict(rule_counter.most_common()),
        "transitions_top20": [
            {"from": a, "to": b, "count": n}
            for (a, b), n in transition_counter.most_common(20)
        ],
        "unmapped_examples": unmapped_examples,
    }
    summary_path = args.out.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"  summary:           {summary_path}")

    print(f"\n  top 12 rules:")
    for rule, n in rule_counter.most_common(12):
        print(f"    {n:>10,}  {rule}")

    print(f"\n  top 12 transitions (current → new):")
    for (a, b), n in transition_counter.most_common(12):
        arrow = "  →" if a != b else " =="
        print(f"    {n:>8,}  {a:<28} {arrow} {b}")

    if unmapped_count:
        print(f"\n  ⚠ UNMAPPED examples (first 20):")
        for prefix, name in unmapped_examples:
            print(f"    prefix={prefix!r:<25} name={name}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
