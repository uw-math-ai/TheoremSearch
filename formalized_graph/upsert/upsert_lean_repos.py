"""Upsert the 15 projects from the corpus SQLite DB into RDS.

Writes one `paper` row (source='Lean Repo', kind='lean_repo') and one
`lean_repo_metadata` row per project, keyed by the repo slug.

Run from the TheoremSearch repo root:
    python formalized_graph/tmp/upsert_lean_repos.py
    python formalized_graph/tmp/upsert_lean_repos.py --overwrite

Without --overwrite, existing rows are left untouched. With --overwrite,
columns that come from the SQLite snapshot are refreshed, but user-curated
URL fields (paper.url, lean_repo_metadata.repo_url) are preserved.
"""

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from rds.utils.connect import get_rds_connection
from rds.utils.upsert import upsert_rows

DEFAULT_DB = Path("/home/ericleonen/TheoremSearch/formalized_graph/corpus_v3.db")
SOURCE = "Lean Repo"
KIND   = "lean_repo"


def _to_utc(ts: str | None) -> datetime | None:
    # SQLite stores naive 'YYYY-MM-DD HH:MM:SS'; tag it UTC for TIMESTAMPTZ.
    if ts is None:
        return None
    return datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB,
                        help=f"Path to corpus SQLite DB. Default: {DEFAULT_DB.name}")
    parser.add_argument("-o", "--overwrite", action="store_true",
                        help="Refresh snapshot columns on conflict. URL fields are always preserved.")
    args = parser.parse_args()

    if not args.db.exists():
        sys.exit(f"missing: {args.db}")

    sconn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    sconn.row_factory = sqlite3.Row
    projects = sconn.execute("""
        SELECT name, url, lean_toolchain, mathlib_rev, git_commit, extracted_at
          FROM projects
         ORDER BY id
    """).fetchall()
    sconn.close()

    paper_rows = []
    meta_rows  = []
    for p in projects:
        slug = p["name"]
        paper_rows.append({
            "kind":        KIND,
            "source":      SOURCE,
            "title":       slug,
            "external_id": slug,
            "url":         p["url"],
            "updated_at":  _to_utc(p["extracted_at"]),
        })
        meta_rows.append({
            "repo_slug":      slug,
            "repo_url":       None,  # populated manually later
            "lean_toolchain": p["lean_toolchain"],
            "mathlib_rev":    p["mathlib_rev"],
            "git_commit":     p["git_commit"],
        })

    paper_conflict = {"with": ["source", "external_id"]}
    meta_conflict  = {"with": ["repo_slug"]}
    if args.overwrite:
        # Intentionally exclude paper.url and repo_url so manually-curated
        # values aren't clobbered on re-ingest.
        paper_conflict["replace"] = ["kind", "title", "updated_at"]
        meta_conflict["replace"]  = ["lean_toolchain", "mathlib_rev", "git_commit"]

    conn = get_rds_connection("v2")
    upsert_rows(conn, table="paper",              rows=paper_rows, on_conflict=paper_conflict)
    upsert_rows(conn, table="lean_repo_metadata", rows=meta_rows,  on_conflict=meta_conflict)
    conn.commit()

    verb = "upserted" if args.overwrite else "submitted (existing rows skipped)"
    print(f"{len(projects)} project rows {verb} into paper + lean_repo_metadata.")


if __name__ == "__main__":
    main()
