"""Build the binary-quantized HNSW index on the embedding table efficiently.

Configures the session for maximum build throughput (bigger
maintenance_work_mem, more parallel maintenance workers) and issues the
non-CONCURRENTLY CREATE INDEX. Polls pg_stat_progress_create_index from a
side thread so you can see what's happening without opening psql yourself.

Run from an EC2 instance (not your laptop) so connection drops don't kill
a multi-hour build, and pre-scale max ACUs in the RDS console first
(e.g. 64).

Usage
-----
    python rds/scripts/build_embedding_hnsw_index.py
    python rds/scripts/build_embedding_hnsw_index.py --maintenance-work-mem 16GB \\
        --max-parallel-maintenance-workers 12 --max-parallel-workers 16

Behaviour
---------
- Index name defaults to ``embedding_binary_hnsw_idx``; aborts if it
  already exists rather than silently doing nothing.
- Connection runs in autocommit so ``SET`` is session-scoped, not
  transaction-scoped, and ``CREATE INDEX`` doesn't sit inside an implicit
  transaction (which would also block any future move to CONCURRENTLY).
- Progress polls every ``--monitor-interval`` seconds (default 60).
- On Ctrl-C, sends ``pg_cancel_backend`` to the build session, then exits.
  No partial index is left behind.
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time

# Allow running from any working directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.connect import get_rds_connection


_INDEX_SQL_TEMPLATE = """
CREATE INDEX {index_name} ON embedding
USING hnsw ((binary_quantize(embedding)::bit(4096)) bit_hamming_ops)
WITH (m = {m}, ef_construction = {ef})
"""


def _index_exists(conn, name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM pg_class WHERE relkind = 'i' AND relname = %s",
            (name,),
        )
        return cur.fetchone() is not None


def _apply_session_knobs(conn, mem: str, mw: int, pw: int) -> None:
    """SET is config syntax, not a regular statement — values are inlined,
    not parameterised. Inputs come from argparse so injection isn't a risk."""
    with conn.cursor() as cur:
        cur.execute(f"SET maintenance_work_mem            = '{mem}'")
        cur.execute(f"SET max_parallel_maintenance_workers = {mw}")
        cur.execute(f"SET max_parallel_workers             = {pw}")


def _monitor(stop: threading.Event, db_kind: str, interval: int) -> None:
    """Tail pg_stat_progress_create_index from a side connection."""
    try:
        conn = get_rds_connection(db_kind)
        conn.autocommit = True
    except Exception as e:
        print(f"  [monitor] could not connect: {e}", flush=True)
        return
    try:
        while not stop.is_set():
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT phase, tuples_done, tuples_total,
                               blocks_done, blocks_total
                          FROM pg_stat_progress_create_index
                    """)
                    rows = cur.fetchall()
                ts = time.strftime("%H:%M:%S")
                if not rows:
                    print(f"  [{ts}] (no active CREATE INDEX visible)", flush=True)
                for phase, t_done, t_total, b_done, b_total in rows:
                    pct = f"{100 * t_done / t_total:6.2f}%" if t_total else "    —  "
                    b_part = f"  blocks={b_done:,}/{b_total:,}" if b_total else ""
                    print(
                        f"  [{ts}] {phase:30s}  tuples={t_done:>10,}/{t_total or 0:>10,} "
                        f"({pct}){b_part}",
                        flush=True,
                    )
            except Exception as e:
                print(f"  [monitor] poll failed: {e}", flush=True)
            stop.wait(interval)
    finally:
        conn.close()


def _cancel_build(db_kind: str, target_query_fragment: str) -> None:
    """Best-effort cancel of the build backend on Ctrl-C."""
    try:
        conn = get_rds_connection(db_kind)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """SELECT pid FROM pg_stat_activity
                   WHERE query LIKE %s AND state != 'idle'""",
                (f"%{target_query_fragment}%",),
            )
            for (pid,) in cur.fetchall():
                cur.execute("SELECT pg_cancel_backend(%s)", (pid,))
                print(f"  sent pg_cancel_backend to pid={pid}")
        conn.close()
    except Exception as e:
        print(f"  cancel failed: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default="v2")
    parser.add_argument("--index-name", default="embedding_binary_hnsw_idx")
    parser.add_argument("--maintenance-work-mem", default="8GB",
                        help="Per-worker maintenance memory. Default: 8GB.")
    parser.add_argument("--max-parallel-maintenance-workers", type=int, default=6,
                        help="Default: 6.")
    parser.add_argument("--max-parallel-workers", type=int, default=8,
                        help="System-wide parallel-workers ceiling. Default: 8.")
    parser.add_argument("--m", type=int, default=32,
                        help="HNSW graph degree. Default: 32.")
    parser.add_argument("--ef-construction", type=int, default=256,
                        help="HNSW build-time candidate list size. Default: 256.")
    parser.add_argument("--monitor-interval", type=int, default=60,
                        help="Seconds between progress polls. 0 disables. Default: 60.")
    args = parser.parse_args()

    sql = _INDEX_SQL_TEMPLATE.format(
        index_name=args.index_name, m=args.m, ef=args.ef_construction
    ).strip()

    print(f"Connecting to RDS ({args.db}) ...")
    conn = get_rds_connection(args.db)
    conn.autocommit = True

    if _index_exists(conn, args.index_name):
        print(f"  index {args.index_name!r} already exists — aborting.")
        print(f"  drop it first: DROP INDEX {args.index_name};")
        sys.exit(1)

    print("Session knobs:")
    print(f"  maintenance_work_mem             = {args.maintenance_work_mem}")
    print(f"  max_parallel_maintenance_workers = {args.max_parallel_maintenance_workers}")
    print(f"  max_parallel_workers             = {args.max_parallel_workers}")
    _apply_session_knobs(
        conn,
        args.maintenance_work_mem,
        args.max_parallel_maintenance_workers,
        args.max_parallel_workers,
    )

    print()
    print(f"Building index {args.index_name} ...")
    print(f"  m = {args.m}, ef_construction = {args.ef_construction}")
    print(f"SQL:\n  {sql}")
    print()

    stop = threading.Event()
    if args.monitor_interval > 0:
        threading.Thread(
            target=_monitor,
            args=(stop, args.db, args.monitor_interval),
            daemon=True,
        ).start()

    t0 = time.perf_counter()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
    except KeyboardInterrupt:
        print("\nCtrl-C received — cancelling the build ...")
        _cancel_build(args.db, args.index_name)
        sys.exit(130)
    finally:
        stop.set()

    elapsed = time.perf_counter() - t0
    print(f"\nDone in {elapsed / 60:.1f} min ({elapsed:.0f}s).")


if __name__ == "__main__":
    main()
