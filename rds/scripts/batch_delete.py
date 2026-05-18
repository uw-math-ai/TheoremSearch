"""
Batch-delete rows from an RDS table that match a given condition.

Usage
-----
    python batch_delete.py --table <table> --condition "<SQL condition>" [--batch-size N] [--db v2]

Examples
--------
    python batch_delete.py --table statement --condition "status = 'error'"
    python batch_delete.py --table paper --condition "created_at < '2024-01-01'" --batch-size 500

Behaviour
---------
- Deletes matching rows in batches of --batch-size (default 1000), committing after each batch.
- If you interrupt with Ctrl-C before a batch is committed, that batch is rolled back.
  Previously committed batches are NOT rolled back (they're already persisted).
- Progress is printed after every batch so you know how far along the operation is.
"""

import argparse
import sys

from tqdm import tqdm

# Allow running from any working directory
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.connect import get_rds_connection

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_matching(cur, table: str, condition: str) -> int:
    cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {condition}")
    return cur.fetchone()[0]


def _delete_batch(cur, table: str, condition: str, batch_size: int) -> int:
    """
    Delete up to *batch_size* rows matching *condition* and return the actual
    number deleted.  Uses ctid so no knowledge of the primary key is required.
    """
    cur.execute(
        f"""
        DELETE FROM {table}
        WHERE ctid IN (
            SELECT ctid
            FROM   {table}
            WHERE  {condition}
            LIMIT  %s
        )
        """,
        (batch_size,),
    )
    return cur.rowcount


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Batch-delete rows from an RDS table matching a condition.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--table",      required=True,  help="Table name to delete from")
    parser.add_argument("--condition",  required=True,  help="SQL WHERE condition (no WHERE keyword)")
    parser.add_argument("--batch-size", type=int, default=1000, help="Rows per batch (default: 1000)")
    parser.add_argument("--db",         default="v2",   help="Database name (default: v2)")
    args = parser.parse_args()

    table      = args.table
    condition  = args.condition
    batch_size = args.batch_size
    db_name    = args.db

    print(f"Connecting to database '{db_name}'…")
    conn = get_rds_connection(db_name)
    conn.autocommit = False  # explicit transaction control

    try:
        with conn.cursor() as cur:
            total_matching = _count_matching(cur, table, condition)

        if total_matching == 0:
            print("No rows match the condition. Nothing to delete.")
            return

        print(f"Found {total_matching:,} rows matching: {condition}")
        print(f"Deleting in batches of {batch_size:,}…\n")

        deleted_total = 0
        batch_num     = 0

        pbar = tqdm(total=total_matching, unit="row", desc="Deleting")

        try:
            while True:
                batch_num += 1

                with conn.cursor() as cur:
                    try:
                        deleted = _delete_batch(cur, table, condition, batch_size)
                    except Exception as exc:
                        conn.rollback()
                        pbar.close()
                        print(f"\nError during batch {batch_num}: {exc}")
                        print("Rolled back the current batch. All previous batches remain committed.")
                        sys.exit(1)

                    if deleted == 0:
                        conn.rollback()  # nothing to commit, but keep state clean
                        break

                    conn.commit()

                deleted_total += deleted
                pbar.update(deleted)

                if deleted < batch_size:
                    # Last batch returned fewer rows than requested — we're done.
                    break

        finally:
            pbar.close()

        print(f"\nDone. Deleted {deleted_total:,} rows.")

    except KeyboardInterrupt:
        conn.rollback()
        print("\n\nInterrupted by user. Rolled back the current (uncommitted) batch.")
        print(f"Rows deleted and committed before interruption: {deleted_total:,}")
        sys.exit(130)  # conventional exit code for Ctrl-C

    finally:
        conn.close()


if __name__ == "__main__":
    main()
