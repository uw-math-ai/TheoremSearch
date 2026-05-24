"""Apply the corpus_v3 paper_id remap to RDS — gated, transactional, verifiable.

Reads `remap_intent.tsv` from a prior dry-run (output of
`dryrun_corpus_v3_remap.py`), then runs ONE UPDATE inside an explicit
transaction that COPYs the remap into a temp table and joins on
`statement_id`. Sanity guards run inside the same transaction and abort
(ROLLBACK) if anything is off.

Three safety knobs:
  --limit N         only apply first N rows of the TSV (rehearsal)
  --no-commit       (default) wrap everything in BEGIN ... ROLLBACK so
                    you see "would update X rows" without persisting
  --apply           required to actually COMMIT. Refuses without it.

Recommended sequence:
  1. python apply_corpus_v3_remap.py --remap <tsv> --limit 100               # 100-row rehearsal
  2. python apply_corpus_v3_remap.py --remap <tsv> --limit 100 --apply       # commit 100
  3. python apply_corpus_v3_remap.py --remap <tsv>                           # full rehearsal
  4. python apply_corpus_v3_remap.py --remap <tsv> --apply                   # full commit

NETWORK: tunnel + .env (AWS_REGION, RDS_SECRET_ARN, RDS_HOST=localhost,
RDS_DBNAME=v2) — same setup as dryrun_corpus_v3_remap.py.
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "formalized_graph" / "upsert"))
from backup_rds_corpus_tables import load_env, get_rds_connection, ENV_PATH  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--remap", type=Path, required=True,
                    help="dry-run TSV (remap_intent.tsv) from dryrun_corpus_v3_remap.py")
    ap.add_argument("--limit", type=int, default=None,
                    help="only apply first N rows of the TSV (rehearsal)")
    ap.add_argument("--apply", action="store_true",
                    help="actually COMMIT. Without this, runs as BEGIN ... ROLLBACK.")
    args = ap.parse_args()

    if not args.remap.exists():
        sys.exit(f"missing --remap TSV: {args.remap}")
    if args.apply and "I_HAVE_REVIEWED_THE_DRYRUN" not in os.environ:
        sys.exit(
            "refusing --apply without I_HAVE_REVIEWED_THE_DRYRUN=yes in env.\n"
            "  Re-run with: I_HAVE_REVIEWED_THE_DRYRUN=yes python ... --apply"
        )

    load_env(ENV_PATH)

    # 1. Read TSV into in-memory CSV-for-COPY buffer.
    #    Columns: statement_id, decl_name, old_paper_id, new_paper_id, old_title, new_project_name
    print(f"reading TSV: {args.remap}", flush=True)
    rows_for_copy = io.StringIO()
    n_rows = 0
    with open(args.remap) as f:
        header = next(f).rstrip("\n").split("\t")
        idx = {c: header.index(c) for c in ("statement_id", "old_paper_id", "new_paper_id")}
        for line in f:
            if args.limit is not None and n_rows >= args.limit:
                break
            parts = line.rstrip("\n").split("\t")
            sid = parts[idx["statement_id"]]
            old = parts[idx["old_paper_id"]]
            new = parts[idx["new_paper_id"]]
            rows_for_copy.write(f"{sid}\t{old}\t{new}\n")
            n_rows += 1
    rows_for_copy.seek(0)
    print(f"  {n_rows:,} remap rows loaded into memory")

    # 2. Connect to RDS — NOT autocommit; we want one explicit transaction.
    print("connecting (tunnel; localhost:5432)...", flush=True)
    conn = get_rds_connection()
    conn.autocommit = False
    cur = conn.cursor()

    t0 = time.time()
    try:
        # 3. Build temp table + COPY in.
        print("creating temp table remap_tmp...", flush=True)
        cur.execute("""
            CREATE TEMP TABLE remap_tmp (
                statement_id  UUID PRIMARY KEY,
                old_paper_id  UUID NOT NULL,
                new_paper_id  UUID NOT NULL
            ) ON COMMIT DROP
        """)
        t_create = time.time()
        print(f"  {t_create-t0:.2f}s")

        print(f"COPY {n_rows:,} rows into remap_tmp...", flush=True)
        cur.copy_expert(
            "COPY remap_tmp (statement_id, old_paper_id, new_paper_id) FROM STDIN WITH (FORMAT csv, DELIMITER E'\\t')",
            rows_for_copy,
        )
        t_copy = time.time()
        print(f"  {t_copy-t_create:.2f}s")

        # 4. Sanity guards inside the same transaction.
        print("sanity guards:", flush=True)

        # 4a. No degenerate rows (old == new)
        cur.execute("SELECT COUNT(*) FROM remap_tmp WHERE old_paper_id = new_paper_id")
        degenerate = cur.fetchone()[0]
        print(f"  rows where old_paper_id = new_paper_id: {degenerate}  (must be 0)")
        if degenerate != 0:
            raise RuntimeError(f"remap has {degenerate} degenerate rows")

        # 4b. Every row's old_paper_id matches the live statement
        cur.execute("""
            SELECT COUNT(*) FROM remap_tmp r
              JOIN statement s USING (statement_id)
             WHERE s.paper_id != r.old_paper_id
        """)
        drifted = cur.fetchone()[0]
        print(f"  rows where live statement.paper_id != old_paper_id: {drifted}  (must be 0)")
        if drifted != 0:
            raise RuntimeError(
                f"{drifted} statements no longer match their old_paper_id "
                "(RDS changed since dry-run was taken — re-run dry-run first)"
            )

        # 4c. Every row's statement_id exists in statement table
        cur.execute("""
            SELECT COUNT(*) FROM remap_tmp r
             WHERE NOT EXISTS (SELECT 1 FROM statement s WHERE s.statement_id = r.statement_id)
        """)
        missing = cur.fetchone()[0]
        print(f"  rows where statement_id not in statement: {missing}  (must be 0)")
        if missing != 0:
            raise RuntimeError(f"{missing} remap rows reference nonexistent statements")

        # 4d. Every new_paper_id exists in paper
        cur.execute("""
            SELECT COUNT(DISTINCT r.new_paper_id) FROM remap_tmp r
             WHERE NOT EXISTS (SELECT 1 FROM paper p WHERE p.paper_id = r.new_paper_id)
        """)
        bad_papers = cur.fetchone()[0]
        print(f"  distinct new_paper_ids not in paper: {bad_papers}  (must be 0)")
        if bad_papers != 0:
            raise RuntimeError(f"{bad_papers} new_paper_ids don't exist")

        t_guards = time.time()
        print(f"  guards passed in {t_guards-t_copy:.2f}s")

        # 5. The UPDATE.
        print("UPDATE statement SET paper_id = new_paper_id FROM remap_tmp ...", flush=True)
        cur.execute("""
            UPDATE statement s
               SET paper_id = r.new_paper_id
              FROM remap_tmp r
             WHERE s.statement_id = r.statement_id
        """)
        rows_updated = cur.rowcount
        t_update = time.time()
        print(f"  {rows_updated:,} rows updated in {t_update-t_guards:.2f}s")

        if rows_updated != n_rows:
            raise RuntimeError(
                f"row count mismatch: TSV had {n_rows:,} but UPDATE touched {rows_updated:,}"
            )

        # 6. Post-update verification: a sample of touched rows now point at new_paper_id
        print("verification sample:", flush=True)
        cur.execute("""
            SELECT s.statement_id, s.paper_id, r.new_paper_id,
                   (s.paper_id = r.new_paper_id) AS match
              FROM remap_tmp r JOIN statement s USING (statement_id)
             ORDER BY random()
             LIMIT 5
        """)
        for row in cur.fetchall():
            sid, live_pid, new_pid, match = row
            print(f"  {str(sid)[:8]}...  live={str(live_pid)[:8]}  expected={str(new_pid)[:8]}  match={match}")

        # 7. Commit or rollback per --apply
        if args.apply:
            print("\n--apply set: COMMITting.", flush=True)
            conn.commit()
            print(f"  committed.")
        else:
            print("\n--apply NOT set: ROLLBACK (no changes persisted).", flush=True)
            conn.rollback()
            print(f"  rolled back.")
    except Exception:
        print("\nERROR — rolling back.", file=sys.stderr, flush=True)
        conn.rollback()
        raise

    t_total = time.time() - t0
    print(f"\ntotal transaction time: {t_total:.2f}s  ({n_rows / t_total:,.0f} rows/s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
