"""Read-only inspection of the corpus_v2 .db file.

Lists every table, its schema, row count, and a few sample rows so we can
plan an upsert into RDS without writing anything back to the SQLite file.
"""

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path("/home/ericleonen/TheoremSearch/corpus_v2_mathlib_plus_v4.27_v4.28_v4.29.db")
SAMPLE_ROWS = 3
MAX_VAL_LEN = 200


def trunc(v):
    s = repr(v)
    return s if len(s) <= MAX_VAL_LEN else s[:MAX_VAL_LEN] + f"...<+{len(s) - MAX_VAL_LEN} chars>"


def main():
    if not DB_PATH.exists():
        sys.exit(f"missing: {DB_PATH}")

    uri = f"file:{DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    print(f"== {DB_PATH.name} ({DB_PATH.stat().st_size / 1e9:.2f} GB) ==\n")

    # All user objects (tables, views, indexes)
    cur.execute("""
        SELECT type, name, tbl_name, sql
          FROM sqlite_master
         WHERE name NOT LIKE 'sqlite_%'
         ORDER BY type, name
    """)
    objects = cur.fetchall()

    tables  = [o for o in objects if o["type"] == "table"]
    views   = [o for o in objects if o["type"] == "view"]
    indexes = [o for o in objects if o["type"] == "index"]
    print(f"tables: {len(tables)}   views: {len(views)}   indexes: {len(indexes)}\n")

    for o in tables:
        name = o["name"]
        print("=" * 70)
        print(f"TABLE  {name}")
        print("-" * 70)
        print(o["sql"] or "(no sql)")
        print()

        # Column info
        cur.execute(f'PRAGMA table_info("{name}")')
        cols = cur.fetchall()
        print("columns:")
        for c in cols:
            pk = " PK" if c["pk"] else ""
            nn = " NOT NULL" if c["notnull"] else ""
            print(f"  - {c['name']:30s} {c['type']:20s}{nn}{pk}")
        print()

        # Row count (may be slow on huge tables but worth knowing)
        cur.execute(f'SELECT COUNT(*) FROM "{name}"')
        n = cur.fetchone()[0]
        print(f"row count: {n:,}")
        print()

        # Sample rows
        if n:
            cur.execute(f'SELECT * FROM "{name}" LIMIT {SAMPLE_ROWS}')
            for i, row in enumerate(cur.fetchall(), 1):
                print(f"sample {i}:")
                for k in row.keys():
                    print(f"  {k:30s} = {trunc(row[k])}")
                print()

    if views:
        print("=" * 70)
        print("VIEWS")
        for v in views:
            print(f"- {v['name']}: {v['sql']}")
        print()

    # Indexes (just names + table)
    if indexes:
        print("=" * 70)
        print("INDEXES")
        for i in indexes:
            print(f"- {i['name']} on {i['tbl_name']}")

    conn.close()


if __name__ == "__main__":
    main()
