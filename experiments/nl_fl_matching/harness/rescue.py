"""Rescue orphaned Aristotle projects whose local subagent died.

Use when:
- A previous run timed out (e.g. 30-min subprocess cap pre-2026-05-24
  bug) but the project is still RUNNING on Aristotle's side.
- You want to attach a digest + trajectory entry to a project that
  finished server-side without us watching.

Usage:
    python3 -m experiments.nl_fl_matching.harness.rescue \
        --label A_martingale_iff_classDL --arm no_graph \
        --project-id ddb6ae7f-4934-47f7-a730-afa2722214c4 \
        --target-file /tmp/simku22/repos/brownian-motion/BrownianMotion/_Harness/A_martingale_iff_classDL__no_graph.lean

Polls `aristotle tasks` every 60s. When the latest task is in a
terminal state (PROVED/PARTIAL/FAILED/ERROR/CANCELED), runs
`aristotle download`, writes a synthetic digest JSON next to the
existing trajectory JSONL (creating a *_rescue.digest.json sibling),
and prints a summary. promote.py picks it up the same way.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from experiments.nl_fl_matching.harness import tools  # noqa: E402

POLL_INTERVAL_S = 60
HARD_TIMEOUT_S = 6 * 3600   # don't sit forever

TERMINAL_STATES = {"PROVED", "PARTIAL", "FAILED", "ERROR", "CANCELED", "CANCELLED", "DONE"}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--label", required=True)
    p.add_argument("--arm", required=True)
    p.add_argument("--project-id", required=True)
    p.add_argument("--target-file", required=True, type=Path,
                   help="The .lean file submitted (for sorry-count comparison).")
    p.add_argument("--project-dir", required=True, type=Path,
                   help="Project worktree (for cwd of aristotle CLI calls).")
    p.add_argument("--existing-trajectory", type=Path, default=None,
                   help="Optional path to the original (timed-out) trajectory JSONL. "
                        "If provided, the rescue digest is written as <traj>_rescue.digest.json.")
    args = p.parse_args()

    pid = args.project_id
    initial_source = args.target_file.read_text() if args.target_file.exists() else ""
    sorry_count_initial = initial_source.count("sorry")

    print(f"[1/3] polling project {pid} every {POLL_INTERVAL_S}s", flush=True)
    t0 = time.time()
    last_status = None
    while True:
        r = tools.aristotle_tasks(pid, cwd=str(args.project_dir))
        status = r.get("latest_task_status")
        if status != last_status:
            print(f"      [{int(time.time()-t0)}s] status={status}", flush=True)
            last_status = status
        if status in TERMINAL_STATES:
            break
        if time.time() - t0 > HARD_TIMEOUT_S:
            print(f"      hard timeout after {HARD_TIMEOUT_S}s; aborting poll", flush=True)
            break
        time.sleep(POLL_INTERVAL_S)

    print(f"[2/3] downloading project files", flush=True)
    dest = args.target_file.parent / f"_rescue_{args.label}_{args.arm}_{pid[:8]}"
    dl = tools.aristotle_download(pid, destination=str(dest), cwd=str(args.project_dir))
    print(f"      ok={dl.get('ok')}  destination={dest}", flush=True)
    if dl.get("stderr"):
        print(f"      stderr: {dl['stderr'][:300]}", flush=True)

    # Find the downloaded version of our target file to count remaining sorries.
    candidate_files = list(dest.rglob(args.target_file.name))
    if candidate_files:
        returned = candidate_files[0].read_text()
        sorry_count_final = returned.count("sorry")
        final_source = returned
    else:
        print(f"      WARN: could not find {args.target_file.name} in download", flush=True)
        sorry_count_final = None
        final_source = ""

    # Map task status to our digest status enum
    status_map = {
        "PROVED": "proved", "PARTIAL": "partial", "FAILED": "failed",
        "ERROR": "error", "CANCELED": "error", "CANCELLED": "error", "DONE": "proved",
    }
    digest = {
        "run_id": str(uuid.uuid4()),
        "candidate_label": args.label,
        "arm": args.arm,
        "status": status_map.get(last_status, "error"),
        "summary": f"Rescued from orphan project {pid}; final task status {last_status}.",
        "sorry_count_initial": sorry_count_initial,
        "sorry_count_final": sorry_count_final,
        "aristotle_submits": 1,
        "aristotle_asks": 0,
        "subagent_turns": 0,     # no subagent — rescue is non-agentic
        "wall_time_s": time.time() - t0,
        "subagent_tokens_in": 0,
        "subagent_tokens_out": 0,
        "trajectory_jsonl_path": str(args.existing_trajectory or ""),
        "subagent_model": "(rescue: no subagent)",
        "final_lean_source": final_source[:8000],
        "rescue": True,
        "aristotle_project_id": pid,
    }
    if args.existing_trajectory:
        out = args.existing_trajectory.with_name(args.existing_trajectory.stem + "_rescue.digest.json")
    else:
        out = dest / "rescue_digest.json"
    out.write_text(json.dumps(digest, default=str, indent=2))
    print(f"[3/3] wrote {out}", flush=True)
    print(json.dumps({k: v for k, v in digest.items() if k != "final_lean_source"},
                     default=str, indent=2))


if __name__ == "__main__":
    main()
