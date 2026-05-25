"""Sweep the subagent across (candidate, arm) pairs.

v1: serial. Run one (candidate, arm) at a time so we can watch the
first few end-to-end before going parallel. Each run produces a JSONL
trajectory under runs/. After the sweep finishes, call
promote.py to push the digest rows to RDS.

Usage:
    python -m experiments.nl_fl_matching.harness.orchestrator \
        --candidates A_martingale_iff_classDL \
        --arms no_graph,with_graph \
        --project-dir /tmp/simku22/repos/brownian-motion
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from experiments.nl_fl_matching.harness.subagent import run as run_subagent  # noqa: E402

HARNESS_DIR = REPO_ROOT / "experiments/nl_fl_matching/harness"
TARGETS_DIR = HARNESS_DIR / "targets"
RUNS_DIR = HARNESS_DIR / "runs"

# Per-candidate target subdirectory under TARGETS_DIR. Each subdir holds
# no_graph.lean + with_graph.lean.
# (We migrate the existing A_martingale_iff_classDL/ here on first run.)
CANDIDATES = {
    "A_martingale_iff_classDL":   HARNESS_DIR / "A_martingale_iff_classDL",
    "B_submartingale_iff_classDL": HARNESS_DIR / "B_submartingale_iff_classDL",
    "F_eta_def":                  HARNESS_DIR / "F_eta_def",
}

# Default project-dir per candidate. The orchestrator's --project-dir
# flag still overrides this (e.g. for one-off testing), but the sweep
# script can pick the right repo automatically if a candidate's
# default differs from the global flag.
CANDIDATE_DEFAULT_PROJECT_DIR = {
    "A_martingale_iff_classDL":    Path("/tmp/simku22/repos/brownian-motion"),
    "B_submartingale_iff_classDL": Path("/tmp/simku22/repos/brownian-motion"),
    "F_eta_def":                   Path("/tmp/simku22/repos/pfr"),
}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--candidates", required=True,
                   help="Comma-separated candidate labels (must be keys of CANDIDATES).")
    p.add_argument("--arms", default="no_graph,with_graph",
                   help="Comma-separated arm names.")
    p.add_argument("--project-dir", type=Path, default=None,
                   help="Lake project root override. If omitted, uses CANDIDATE_DEFAULT_PROJECT_DIR per candidate.")
    p.add_argument("--target-subdir-in-project", default=None,
                   help="Relative path inside project-dir where target lean files land. "
                        "Defaults to <RootModule>/_Harness based on the project (BrownianMotion or PFR).")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would happen; don't call Anthropic or Aristotle.")
    args = p.parse_args()

    cands = [c.strip() for c in args.candidates.split(",") if c.strip()]
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]

    for c in cands:
        if c not in CANDIDATES:
            print(f"ERROR: unknown candidate {c}. Known: {list(CANDIDATES)}", file=sys.stderr)
            sys.exit(2)

    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    digests = []
    for cand in cands:
        cand_dir = CANDIDATES[cand]
        # Per-candidate project dir; --project-dir overrides for all.
        project_dir = (args.project_dir or CANDIDATE_DEFAULT_PROJECT_DIR[cand]).resolve()
        # Default subdir: <project root module>/_Harness.
        subdir = args.target_subdir_in_project
        if not subdir:
            # heuristic: brownian-motion → BrownianMotion, pfr → PFR
            subdir = f"{project_dir.name.replace('-', '_').title().replace('_', '')}/_Harness"
            # crude title-case fix for common cases
            if "brownian" in project_dir.name.lower():
                subdir = "BrownianMotion/_Harness"
            elif project_dir.name.lower() == "pfr":
                subdir = "PFR/_Harness"
        target_subdir_abs = project_dir / subdir
        target_subdir_abs.mkdir(parents=True, exist_ok=True)

        for arm in arms:
            src = cand_dir / f"{arm}.lean"
            if not src.exists():
                print(f"SKIP {cand}/{arm}: file not found at {src}", file=sys.stderr)
                continue

            # Stage: copy the .lean file into the project's harness subdir.
            # We copy (not symlink) so aristotle sees a real file in the
            # project tree. Filename includes arm so both arms can coexist
            # if anyone wants to compare side-by-side later.
            staged = target_subdir_abs / f"{cand}__{arm}.lean"
            staged.write_text(src.read_text())

            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            traj_path = RUNS_DIR / f"{cand}__{arm}__{ts}.jsonl"

            print(f"\n=== {cand} / {arm} ===", flush=True)
            print(f"  staged target: {staged}", flush=True)
            print(f"  trajectory   : {traj_path}", flush=True)

            if args.dry_run:
                print("  (dry-run; skipping subagent)", flush=True)
                continue

            t0 = time.time()
            digest = run_subagent(
                candidate_label=cand, arm=arm,
                target_path=staged, project_dir=project_dir,
                trajectory_path=traj_path,
            )
            print(f"  status={digest['status']}  "
                  f"submits={digest['aristotle_submits']}  "
                  f"asks={digest['aristotle_asks']}  "
                  f"turns={digest['subagent_turns']}  "
                  f"wall={digest['wall_time_s']:.1f}s", flush=True)
            digests.append(digest)

            # Write a tiny manifest next to the jsonl so promote.py can
            # find it without rerunning the agent.
            (traj_path.with_suffix(".digest.json")).write_text(
                json.dumps(digest, default=str, indent=2)
            )

    print("\n=== sweep summary ===")
    for d in digests:
        print(f"  {d['candidate_label']:35s} {d['arm']:10s} {d['status']:18s} "
              f"sorry {d['sorry_count_initial']}→{d['sorry_count_final']}")


if __name__ == "__main__":
    main()
