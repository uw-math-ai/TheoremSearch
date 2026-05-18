#!/usr/bin/env python3
"""
Type-check F_B, F_T, F_Tnames, F_Trandom against Mathlib v4.29.0.

First run (once): cd lean_typecheck && lake exe cache get
Then: python3 run_typecheck.py

Strategy: batch all N declarations for a given condition into one .lean file,
paying the `import Mathlib` cost once per condition (~12s) instead of once per
candidate (~12s × N). Each declaration is wrapped in a uniquely-named namespace
to avoid name collisions with Mathlib and each other. Errors are parsed by line
number to map back to candidates.

Exit code 0 on a declaration = type-checks (sorry warnings are fine).
"""

import argparse
import csv
import re
import subprocess
import tempfile
import time
from pathlib import Path

REPO     = Path(__file__).resolve().parents[2]
LEAN_DIR = Path(__file__).parent / "lean_typecheck"
LAKE     = Path.home() / ".elan/bin/lake"
LEAN     = Path.home() / ".elan/bin/lean"
TIMEOUT  = 300  # seconds per condition batch


def strip_fences(text):
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return text.strip()


def batch_typecheck(decls: list[tuple[str, str]]) -> dict[str, bool]:
    """
    decls: list of (key, declaration_text)
    Returns dict key -> bool (True = type-checks).
    Wraps each in `namespace Check_<key> ... end Check_<key>` to isolate.
    Parses stderr for error lines to determine per-key pass/fail.
    """
    if not decls:
        return {}

    lines = ["import Mathlib", "set_option maxHeartbeats 400000", ""]
    # Track which line each namespace block starts on (1-indexed)
    namespace_start: dict[str, int] = {}
    current_line = 3  # after header

    for key, decl_text in decls:
        decl = strip_fences(decl_text)
        if not decl:
            lines += [f"-- EMPTY: {key}", ""]
            current_line += 2
            continue
        ns = f"Check_{re.sub(r'[^a-zA-Z0-9]', '_', key)}"
        namespace_start[key] = current_line
        block = [f"namespace {ns}", decl, f"end {ns}", ""]
        lines += block
        current_line += len(block)

    src = "\n".join(lines)

    with tempfile.NamedTemporaryFile(
        suffix=".lean", mode="w", dir=LEAN_DIR, delete=False
    ) as f:
        f.write(src)
        tmp = Path(f.name)

    try:
        result = subprocess.run(
            [str(LAKE), "env", str(LEAN), str(tmp.name)],
            cwd=LEAN_DIR,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        stderr = result.stderr + result.stdout

        # Find all error line numbers reported by Lean
        # Format: "/path/to/file.lean:LINE:COL: error: ..."
        error_lines: set[int] = set()
        for m in re.finditer(rf"{re.escape(tmp.name)}:(\d+):\d+: error:", stderr):
            error_lines.add(int(m.group(1)))

        # Map each key to pass/fail based on whether any error falls within its block
        results: dict[str, bool] = {}
        sorted_keys = list(namespace_start.keys())
        # Build line ranges: key i owns lines [start_i, start_{i+1})
        for i, key in enumerate(sorted_keys):
            start = namespace_start[key]
            end = namespace_start[sorted_keys[i + 1]] if i + 1 < len(sorted_keys) else current_line
            has_error = any(start <= ln < end for ln in error_lines)
            results[key] = not has_error

        # Keys with empty decls default to False
        for key, _ in decls:
            if key not in results:
                results[key] = False

        return results

    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT on batch of {len(decls)}")
        return {key: False for key, _ in decls}
    finally:
        tmp.unlink(missing_ok=True)


def run_condition(label: str, rows: list[dict], decl_col: str) -> dict[str, bool]:
    """Type-check one condition column across all rows. Returns {node_id_str: bool}."""
    print(f"  Checking {label} ({len(rows)} declarations)...", end="", flush=True)
    t0 = time.time()
    pairs = [(str(r["node_id"]), r.get(decl_col, "")) for r in rows]
    results = batch_typecheck(pairs)
    n_ok = sum(results.values())
    print(f" {n_ok}/{len(rows)} pass  ({time.time()-t0:.1f}s)")
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-cache-check", action="store_true")
    args = parser.parse_args()

    out_dir = Path(__file__).parent

    if not LAKE.exists():
        raise SystemExit(f"lake not found at {LAKE}")

    if not args.skip_cache_check:
        print("Checking Mathlib cache...")
        subprocess.run([str(LAKE), "exe", "cache", "get"], cwd=LEAN_DIR, timeout=3600)

    # ── Pilot CSV (F_B, F_T) ─────────────────────────────────────────────────
    pilot_path = out_dir / "results.csv"
    pilot_rows = list(csv.DictReader(open(pilot_path)))
    print(f"\nPilot ({pilot_path.name}): {len(pilot_rows)} candidates")

    tc_B = run_condition("F_B",   pilot_rows, "F_B")
    tc_T = run_condition("F_T",   pilot_rows, "F_T")

    pilot_cols = list(csv.DictReader(open(pilot_path)).fieldnames)
    for col in ("typecheck_B", "typecheck_T"):
        if col not in pilot_cols:
            pilot_cols.append(col)
    for row in pilot_rows:
        nid = str(row["node_id"])
        row["typecheck_B"] = tc_B.get(nid, False)
        row["typecheck_T"] = tc_T.get(nid, False)
    with open(pilot_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=pilot_cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(pilot_rows)
    print(f"  Updated {pilot_path.name}")

    # ── Ablation CSV (F_T, F_Tnames, F_Trandom) ──────────────────────────────
    abl_path = out_dir / "ablation_results.csv"
    if not abl_path.exists():
        print(f"\n{abl_path.name} not found — skipping ablation type-checks.")
        return

    abl_rows = list(csv.DictReader(open(abl_path)))
    print(f"\nAblation ({abl_path.name}): {len(abl_rows)} candidates")

    tc_aT      = run_condition("F_T",      abl_rows, "F_T")
    tc_Tnames  = run_condition("F_Tnames", abl_rows, "F_Tnames")
    tc_Trandom = run_condition("F_Trandom",abl_rows, "F_Trandom")

    abl_cols = list(csv.DictReader(open(abl_path)).fieldnames)
    for col in ("typecheck_T", "typecheck_Tnames", "typecheck_Trandom"):
        if col not in abl_cols:
            abl_cols.append(col)
    for row in abl_rows:
        nid = str(row["node_id"])
        row["typecheck_T"]       = tc_aT.get(nid, False)
        row["typecheck_Tnames"]  = tc_Tnames.get(nid, False)
        row["typecheck_Trandom"] = tc_Trandom.get(nid, False)
    with open(abl_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=abl_cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(abl_rows)
    print(f"  Updated {abl_path.name}")

    print("\nDone.")


if __name__ == "__main__":
    main()
