"""Promote good JSONL trajectories to RDS table prover_run.

Filters: only promote runs whose status is in PROMOTABLE_STATUSES and
whose trajectory file exists and parses cleanly. This is the "JSONL
primary, write to RDS once they're good" pattern.

Usage:
    RDS_HOST=theorem-search.cluster-cx0ei6kq0qcn.us-west-2.rds.amazonaws.com \
        python3 -m experiments.nl_fl_matching.harness.promote
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "rds"))

from utils.connect import get_rds_connection  # noqa: E402

RUNS_DIR = REPO_ROOT / "experiments/nl_fl_matching/harness/runs"
SCHEMA_PATH = REPO_ROOT / "experiments/nl_fl_matching/harness/prover_run_schema.sql"

PROMOTABLE_STATUSES = {"proved", "partial", "failed", "budget_exhausted"}

# Hand-managed label → candidate_statement_id (UUID in `statement`)
# Update when adding new candidates.
LABEL_TO_SID = {
    "A_martingale_iff_classDL": "b8f7c652-f29c-48cb-9b59-8c8652e3699f",
    "B_submartingale_iff_classDL": "5cfea075-c00e-43d2-8ca7-d76f51b3e92c",
    "F_eta_def": "3be0d32c-3c33-4b86-9d33-4a18c69d2c20",
}


def main():
    conn = get_rds_connection("v2")
    with conn.cursor() as cur:
        for stmt in SCHEMA_PATH.read_text().split(";"):
            if stmt.strip():
                cur.execute(stmt + ";")
        conn.commit()

    digest_files = sorted(RUNS_DIR.glob("*.digest.json"))
    promoted = skipped = 0
    for f in digest_files:
        try:
            d = json.loads(f.read_text())
        except Exception as e:
            print(f"  SKIP {f.name}: parse error {e}")
            skipped += 1
            continue

        if d.get("status") not in PROMOTABLE_STATUSES:
            print(f"  SKIP {f.name}: status={d.get('status')!r}")
            skipped += 1
            continue

        cand_sid = LABEL_TO_SID.get(d["candidate_label"])
        if not cand_sid:
            print(f"  SKIP {f.name}: no statement_id mapping for {d['candidate_label']}")
            skipped += 1
            continue

        # Use the run's existing attempt number = count of prior promoted runs
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COALESCE(MAX(attempt_n), 0) + 1
                  FROM prover_run
                 WHERE candidate_statement_id = %s AND arm = %s
            """, (cand_sid, d["arm"]))
            attempt_n = cur.fetchone()[0]

            cur.execute("""
                INSERT INTO prover_run (
                    run_id, candidate_statement_id, candidate_label, arm, attempt_n,
                    prover, subagent_model, status,
                    sorry_count_initial, sorry_count_final,
                    aristotle_submits, aristotle_asks, subagent_turns,
                    wall_time_s, subagent_tokens_in, subagent_tokens_out,
                    trajectory_jsonl_path, final_lean_source
                ) VALUES (
                    %(run_id)s, %(cand_sid)s, %(candidate_label)s, %(arm)s, %(attempt_n)s,
                    'aristotle', %(subagent_model)s, %(status)s,
                    %(s0)s, %(s1)s,
                    %(submits)s, %(asks)s, %(turns)s,
                    %(wall)s, %(tin)s, %(tout)s,
                    %(traj)s, %(final)s
                )
                ON CONFLICT (candidate_statement_id, arm, attempt_n) DO NOTHING
            """, dict(
                run_id=d["run_id"], cand_sid=cand_sid,
                candidate_label=d["candidate_label"], arm=d["arm"], attempt_n=attempt_n,
                subagent_model=d.get("subagent_model"), status=d["status"],
                s0=d.get("sorry_count_initial"), s1=d.get("sorry_count_final"),
                submits=d.get("aristotle_submits", 0), asks=d.get("aristotle_asks", 0),
                turns=d.get("subagent_turns", 0),
                wall=d.get("wall_time_s"),
                tin=d.get("subagent_tokens_in"), tout=d.get("subagent_tokens_out"),
                traj=d.get("trajectory_jsonl_path"),
                final=d.get("final_lean_source"),
            ))
        promoted += 1
        print(f"  PROMOTED {f.name} → attempt_n={attempt_n}")
    conn.commit()
    print(f"\n{promoted} promoted, {skipped} skipped")


if __name__ == "__main__":
    main()
