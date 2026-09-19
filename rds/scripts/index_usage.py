"""Snapshot index/table scan counters in the `postgres` (v1) and `v2`
databases, or diff the current counters against an earlier snapshot.

The counters (pg_stat_user_indexes / pg_stat_user_tables) have never been
reset, so on their own they only show lifetime use. Diffing two snapshots a
few days apart shows what is actually used now, e.g. before dropping v1
indexes. Read-only.

Usage
-----
    python rds/scripts/index_usage.py                          # write rds/usage/usage_<time>.json
    python rds/scripts/index_usage.py rds/usage/usage_X.json   # diff against it (and write a new one)
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.connect import get_rds_connection

_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "usage")
_SQL_IDX = "SELECT indexrelname, relname, idx_scan FROM pg_stat_user_indexes"
_SQL_TBL = "SELECT relname, seq_scan, coalesce(idx_scan, 0) FROM pg_stat_user_tables"


def snapshot() -> dict:
    snap = {"at": datetime.datetime.now().isoformat(timespec="seconds")}
    for db in ("postgres", "v2"):
        conn = get_rds_connection(db)
        conn.set_session(readonly=True)
        with conn.cursor() as cur:
            cur.execute(_SQL_IDX)
            snap[f"{db}:idx"] = {r[0]: [r[1], r[2]] for r in cur.fetchall()}
            cur.execute(_SQL_TBL)
            snap[f"{db}:tbl"] = {r[0]: [r[1], r[2]] for r in cur.fetchall()}
        conn.close()
    return snap


def diff(old: dict, new: dict) -> None:
    print(f"Scans between {old['at']} and {new['at']}:")
    for key in ("postgres:idx", "postgres:tbl", "v2:idx", "v2:tbl"):
        print(f"\n[{key}]")
        for name, cur in sorted(new[key].items()):
            prev = old[key].get(name)
            if prev is None:
                print(f"  {name:60s} (new)")
            elif key.endswith("idx"):
                print(f"  {name:60s} {cur[1] - prev[1]:>10,} scans   (table {cur[0]})")
            else:
                print(f"  {name:60s} {cur[0] - prev[0]:>10,} seq  {cur[1] - prev[1]:>10,} idx")


def main() -> None:
    new = snapshot()
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            diff(json.load(f), new)
    os.makedirs(_OUT_DIR, exist_ok=True)
    out = os.path.join(_OUT_DIR, "usage_" + new["at"].replace(":", "") + ".json")
    with open(out, "w") as f:
        json.dump(new, f)
    print(f"\nsnapshot written to {out}")


if __name__ == "__main__":
    main()
