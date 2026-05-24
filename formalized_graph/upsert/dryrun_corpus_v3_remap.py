"""Dry-run the corpus_v3 paper_id remap against RDS — READ-ONLY.

Source of truth: `corpus_v3 (corrected ingestion order).db` — a one-off
rebuild of corpus_v3.db where Mathlib_v427 → v428 → v429 → Batteries →
community projects were ingested in deterministic order, so each shared
declaration is owned by the project that *actually* first introduces it
(rather than the alphabetical-first claimant in the canonical wrong-order
ingest).

For every RDS `statement` row whose `formal_metadata.decl_name` exists in
the ordered DB, this script computes:

  - the statement's current `paper_id` (from RDS)
  - the correct `paper_id` (from ordered DB → project name → Lean Repo
    paper via paper.external_id)
  - whether they differ → emit a remap row

This script does NOT modify RDS. It writes:
  - `remap_intent.tsv`  — one row per RDS statement that would change
  - `report.json`       — aggregate counters (transitions, unresolved, samples)
  - human-readable summary to stdout

Per the agreed plan, this script *fails loudly* if any RDS formal_metadata
decl_name doesn't resolve in the ordered DB (would indicate stale data or a
naming mismatch that needs investigation before any apply).

NETWORK: requires an SSH tunnel from localhost:5432 to the RDS endpoint,
+ .env with AWS_REGION / RDS_SECRET_ARN at TheoremSearch root.

Usage (with tunnel already up):
  set -a; source /mmfs1/gscratch/amath/simku22/TheoremSearch/.env; set +a
  export RDS_HOST=localhost RDS_DBNAME=v2
  python3.12 formalized_graph/upsert/dryrun_corpus_v3_remap.py
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# Re-use the connection helper from the backup script. We import via a path
# tweak so the module doesn't need to be on sys.path.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "formalized_graph" / "upsert"))
from backup_rds_corpus_tables import load_env, get_rds_connection, ENV_PATH  # noqa: E402

SOURCE = "Lean Repo"  # paper.source for the corpus_v3 projects (per upsert_lean_repos.py)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--ordered-db",
        type=Path,
        default=Path("/gscratch/amath/simku22/corpus_v3_fixed/corpus_v3 (corrected ingestion order).db"),
        help="SQLite DB whose project_id is the source of truth for new paper_id",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path("/gscratch/amath/simku22/corpus_v3_fixed/remap_dryrun"),
        help="output directory for report + TSV (timestamped subdir created inside)",
    )
    ap.add_argument(
        "--sample-size",
        type=int,
        default=10,
        help="number of moved-statement examples to include in the report",
    )
    args = ap.parse_args()

    if not args.ordered_db.exists():
        sys.exit(f"missing --ordered-db: {args.ordered_db}")

    load_env(ENV_PATH)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out_dir / f"dryrun_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(out_dir, 0o700)
    print(f"output dir: {out_dir}", flush=True)

    # 1. Build {decl_name → project_name} from ordered DB (the truth).
    print(f"\nloading ordered DB: {args.ordered_db}", flush=True)
    odb = sqlite3.connect(f"file:{args.ordered_db}?mode=ro&immutable=1", uri=True)
    project_count = odb.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    node_count = odb.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    print(f"  {project_count} projects, {node_count:,} nodes")
    decl_to_project: dict[str, str] = dict(
        odb.execute(
            "SELECT n.full_name, p.name FROM nodes n JOIN projects p ON p.id = n.project_id"
        )
    )
    print(f"  {len(decl_to_project):,} (decl_name → project) entries loaded")
    odb.close()

    # 2. Connect to RDS (read-only operations).
    print("\nconnecting to RDS (via tunnel; expects RDS_HOST=localhost)...", flush=True)
    conn = get_rds_connection()
    conn.set_session(readonly=True, autocommit=True)
    print("  connected.")

    # 3. project name → paper_id, scoped to Lean Repo source.
    cur = conn.cursor()
    cur.execute("SELECT external_id, paper_id, title FROM paper WHERE source = %s", (SOURCE,))
    rows = cur.fetchall()
    paper_by_slug = {r[0]: r[1] for r in rows}
    title_by_paper = {r[1]: r[2] for r in rows}
    print(f"  resolved {len(paper_by_slug)} Lean Repo papers from RDS")

    # Sanity: ensure every project in ordered DB has a paper in RDS.
    project_names_ordered = set(decl_to_project.values())
    missing_papers = project_names_ordered - set(paper_by_slug)
    if missing_papers:
        print(f"\n  ⚠ projects in ordered DB with no Lean Repo paper in RDS:")
        for p in sorted(missing_papers):
            print(f"    {p}")
        print("\n  These decls cannot be remapped. They would be reported as unresolved.")

    # 4. Stream every formal statement and compute its intended new paper_id.
    print("\nstreaming RDS formal statements...", flush=True)
    cur.execute(
        """
        SELECT s.statement_id, s.paper_id, fm.decl_name
          FROM statement s
          JOIN formal_metadata fm ON fm.statement_id = s.statement_id
        """
    )
    moves = []  # (statement_id, decl_name, old_paper_id, new_paper_id, old_project, new_project)
    stays = 0
    unresolved_no_decl_in_ordered = []
    unresolved_no_paper_for_project = []
    n_total = 0

    chunk = 5000
    while True:
        batch = cur.fetchmany(chunk)
        if not batch:
            break
        for sid, current_paper_id, decl_name in batch:
            n_total += 1
            new_project = decl_to_project.get(decl_name)
            if new_project is None:
                unresolved_no_decl_in_ordered.append((str(sid), decl_name))
                continue
            new_paper_id = paper_by_slug.get(new_project)
            if new_paper_id is None:
                unresolved_no_paper_for_project.append((str(sid), decl_name, new_project))
                continue
            if str(new_paper_id) == str(current_paper_id):
                stays += 1
            else:
                old_project = title_by_paper.get(current_paper_id, "?")
                moves.append(
                    (
                        str(sid),
                        decl_name,
                        str(current_paper_id),
                        str(new_paper_id),
                        old_project,
                        new_project,
                    )
                )
    print(f"  total formal statements scanned: {n_total:,}")
    print(f"  unchanged (stays under same paper): {stays:,}")
    print(f"  would move to new paper:            {len(moves):,}")
    print(f"  unresolved (decl not in ordered):   {len(unresolved_no_decl_in_ordered):,}")
    print(f"  unresolved (no paper for project):  {len(unresolved_no_paper_for_project):,}")

    # 5. Persist outputs.
    tsv_path = out_dir / "remap_intent.tsv"
    with open(tsv_path, "w") as f:
        f.write("statement_id\tdecl_name\told_paper_id\tnew_paper_id\told_project_title\tnew_project_name\n")
        for row in moves:
            f.write("\t".join(row) + "\n")
    os.chmod(tsv_path, 0o600)
    print(f"\nwrote {tsv_path} ({tsv_path.stat().st_size:,} bytes; {len(moves):,} rows)")

    # Transition counter (old project → new project)
    transitions: Counter[tuple[str, str]] = Counter()
    for sid, _, _, _, op, np_ in moves:
        transitions[(op, np_)] += 1

    sample = random.Random(42).sample(moves, min(args.sample_size, len(moves))) if moves else []

    report = {
        "created_at": ts,
        "ordered_db": str(args.ordered_db),
        "rds_source_label": SOURCE,
        "totals": {
            "formal_statements_scanned": n_total,
            "stays_same": stays,
            "would_move": len(moves),
            "unresolved_no_decl_in_ordered": len(unresolved_no_decl_in_ordered),
            "unresolved_no_paper_for_project": len(unresolved_no_paper_for_project),
        },
        "transitions": [
            {"from_title": a, "to_project": b, "count": n}
            for (a, b), n in transitions.most_common()
        ],
        "sample_moves": [
            {
                "statement_id": sid,
                "decl_name": dn,
                "old_paper_id": op_id,
                "new_paper_id": np_id,
                "old_project_title": op,
                "new_project_name": np_,
            }
            for sid, dn, op_id, np_id, op, np_ in sample
        ],
        "unresolved_no_decl_in_ordered_examples": unresolved_no_decl_in_ordered[:20],
        "unresolved_no_paper_for_project_examples": unresolved_no_paper_for_project[:20],
    }
    report_path = out_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2))
    os.chmod(report_path, 0o600)
    print(f"wrote {report_path}")

    # 6. Human summary
    print(f"\n  === transitions (top 20: old_title → new_project) ===")
    for (a, b), n in transitions.most_common(20):
        print(f"    {n:>8,}  {a or '(?)':<30} → {b}")

    if sample:
        print(f"\n  === sample of {len(sample)} moves ===")
        for sid, dn, op_id, np_id, op, np_ in sample[:10]:
            print(f"    decl_name={dn}")
            print(f"      statement_id={sid}")
            print(f"      from: {op or '?'}  ({op_id})")
            print(f"      to:   {np_}  ({np_id})")

    # 7. Fail-loud policy
    if unresolved_no_decl_in_ordered or unresolved_no_paper_for_project:
        print(
            f"\n  ⚠ UNRESOLVED — investigate before any apply:"
            f"\n    decl not in ordered DB:        {len(unresolved_no_decl_in_ordered):,}"
            f"\n    no Lean Repo paper for proj:   {len(unresolved_no_paper_for_project):,}"
        )
        if unresolved_no_decl_in_ordered:
            print(f"\n    first 5 'decl not in ordered':")
            for sid, dn in unresolved_no_decl_in_ordered[:5]:
                print(f"      sid={sid}  decl_name={dn}")
        if unresolved_no_paper_for_project:
            print(f"\n    first 5 'no paper':")
            for sid, dn, proj in unresolved_no_paper_for_project[:5]:
                print(f"      sid={sid}  decl_name={dn}  → project={proj}")
        return 1

    print("\n  OK — every formal statement resolved cleanly. Apply is safe to attempt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
