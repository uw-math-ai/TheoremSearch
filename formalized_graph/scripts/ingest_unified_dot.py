#!/usr/bin/env python3
"""
Ingest a unified DOT graph (produced by lean-graph's `lake exe graph --mode unified`)
into the TheoremSearch formalized_graph corpus DB.

Handles both:
  - A fresh project-specific DB (default): writes nodes+edges from the DOT.
  - The existing global_corpus.db: inserts the project as a new record and
    merges nodes/edges, deduplicating by full_name.

Usage:
    python3 formalized_graph/scripts/ingest_unified_dot.py \
        --dot   /path/to/output.dot \
        --nodes /path/to/output_nodes.csv \
        --db    formalized_graph/data/generated/sphere_eversion_unified.db \
        --project SphereEversion

    # Merge into global corpus instead:
    python3 formalized_graph/scripts/ingest_unified_dot.py \
        --dot   output.dot --nodes nodes.csv \
        --db    formalized_graph/data/generated/global_corpus.db \
        --project SphereEversion --global-db
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from pathlib import Path

# DOT → DB kind normalization (matches convert_unified.py)
KIND_MAP = {
    "sig":     "signature",
    "extends": "extends",
    "field":   "field",
    "proof":   "proof",
    "def":     "def",
    "docref":  "docref",
}

_EDGE_RE = re.compile(r'^\s*"([^"]+)"\s*->\s*"([^"]+)"\s*\[([^\]]*)\]')
_KIND_RE = re.compile(r'\bkind="?([^",\]\s]+)"?')
_FIELD_RE = re.compile(r'"([^"]*)"')


# ── Schema ────────────────────────────────────────────────────────────────────

FRESH_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    name      TEXT PRIMARY KEY,
    decl_type TEXT NOT NULL DEFAULT '',
    module    TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS edges (
    src  TEXT NOT NULL,
    dst  TEXT NOT NULL,
    kind TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_src  ON edges(src);
CREATE INDEX IF NOT EXISTS idx_dst  ON edges(dst);
CREATE INDEX IF NOT EXISTS idx_kind ON edges(kind);
"""

# The global_corpus.db uses the existing schema with integer PKs.
# We add kind + decl_type + module columns if missing.
GLOBAL_MIGRATE = """
ALTER TABLE nodes ADD COLUMN decl_type TEXT NOT NULL DEFAULT '';
ALTER TABLE nodes ADD COLUMN module    TEXT NOT NULL DEFAULT '';
ALTER TABLE edges ADD COLUMN kind      TEXT NOT NULL DEFAULT 'proof';
"""


# ── Loaders ───────────────────────────────────────────────────────────────────

def load_nodes_csv(path: Path) -> list[tuple[str, str, str]]:
    """Parse nodes CSV → list of (name, decl_type, module)."""
    rows: list[tuple[str, str, str]] = []
    if not path.exists():
        print(f"  Warning: nodes CSV not found at {path}, skipping node metadata.", file=sys.stderr)
        return rows
    with path.open(encoding="utf-8") as f:
        f.readline()  # header
        for line in f:
            fields = _FIELD_RE.findall(line.rstrip("\n"))
            if len(fields) >= 3:
                rows.append((fields[0], fields[1], fields[2]))
    return rows


def stream_edges(dot_path: Path):
    """Yield (src, dst, kind) from a unified DOT file."""
    with dot_path.open(encoding="utf-8") as f:
        for line in f:
            m = _EDGE_RE.match(line)
            if not m:
                continue
            src, dst, attrs = m.group(1), m.group(2), m.group(3)
            km = _KIND_RE.search(attrs)
            if not km:
                continue
            kind = KIND_MAP.get(km.group(1), km.group(1))
            yield src, dst, kind


# ── Fresh DB (project-specific) ───────────────────────────────────────────────

def ingest_fresh(dot_path: Path, nodes_csv: Path, db_path: Path) -> None:
    """Write a standalone unified.db mirroring lean-graph's own schema."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    conn.executescript(FRESH_SCHEMA)
    conn.commit()

    t0 = time.time()

    # Nodes
    node_rows = load_nodes_csv(nodes_csv)
    conn.executemany(
        "INSERT OR REPLACE INTO nodes(name, decl_type, module) VALUES (?, ?, ?)",
        node_rows,
    )
    conn.commit()
    print(f"  Nodes: {len(node_rows):,}  ({time.time()-t0:.1f}s)")

    # Edges (streaming)
    batch: list[tuple[str, str, str]] = []
    BATCH = 50_000
    n_edges = 0
    t1 = time.time()
    for edge in stream_edges(dot_path):
        batch.append(edge)
        n_edges += 1
        if len(batch) >= BATCH:
            conn.executemany("INSERT INTO edges(src, dst, kind) VALUES (?, ?, ?)", batch)
            conn.commit()
            batch.clear()
            if n_edges % 500_000 == 0:
                print(f"  {n_edges:,} edges  ({time.time()-t1:.1f}s)")
    if batch:
        conn.executemany("INSERT INTO edges(src, dst, kind) VALUES (?, ?, ?)", batch)
        conn.commit()

    print(f"  Edges: {n_edges:,}  ({time.time()-t1:.1f}s)")
    _print_stats(conn)
    conn.close()


# ── Global corpus DB ──────────────────────────────────────────────────────────

def _migrate_global(conn: sqlite3.Connection) -> None:
    for stmt in GLOBAL_MIGRATE.strip().splitlines():
        stmt = stmt.strip()
        if not stmt:
            continue
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()


def ingest_global(dot_path: Path, nodes_csv: Path, db_path: Path, project_name: str) -> None:
    """Merge unified graph into the existing global_corpus.db."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _migrate_global(conn)

    # Add project record
    conn.execute(
        "INSERT OR IGNORE INTO projects(name, is_mathlib) VALUES (?, 0)",
        (project_name,),
    )
    conn.commit()
    project_id = conn.execute(
        "SELECT id FROM projects WHERE name = ?", (project_name,)
    ).fetchone()[0]

    t0 = time.time()

    # Nodes — upsert into the integer-PK nodes table
    node_rows = load_nodes_csv(nodes_csv)
    for name, decl_type, module in node_rows:
        conn.execute(
            """
            INSERT OR IGNORE INTO nodes
                (project_id, full_name, kind, decl_type, module)
            VALUES (?, ?, ?, ?, ?)
            """,
            (project_id, name, decl_type, module, ""),
        )
        conn.execute(
            "UPDATE nodes SET decl_type=?, module=? WHERE full_name=? AND (decl_type='' OR decl_type IS NULL)",
            (decl_type, module, name),
        )
    conn.commit()
    print(f"  Nodes: {len(node_rows):,}  ({time.time()-t0:.1f}s)")

    # Resolve name → id map for edge insertion
    id_map: dict[str, int] = {
        row["full_name"]: row["id"]
        for row in conn.execute("SELECT id, full_name FROM nodes")
    }

    # Edges — insert with kind, resolving text names to integer IDs
    batch: list[tuple[int, int, str]] = []
    BATCH = 50_000
    n_edges = 0
    n_skipped = 0
    t1 = time.time()
    for src, dst, kind in stream_edges(dot_path):
        src_id = id_map.get(src)
        dst_id = id_map.get(dst)
        if src_id is None or dst_id is None:
            n_skipped += 1
            continue
        batch.append((src_id, dst_id, kind))
        n_edges += 1
        if len(batch) >= BATCH:
            conn.executemany(
                "INSERT OR IGNORE INTO edges(source_id, target_id, kind) VALUES (?, ?, ?)",
                batch,
            )
            conn.commit()
            batch.clear()
            if n_edges % 500_000 == 0:
                print(f"  {n_edges:,} edges  ({time.time()-t1:.1f}s)")
    if batch:
        conn.executemany(
            "INSERT OR IGNORE INTO edges(source_id, target_id, kind) VALUES (?, ?, ?)",
            batch,
        )
        conn.commit()

    print(f"  Edges: {n_edges:,} inserted, {n_skipped:,} skipped (unknown nodes)  ({time.time()-t1:.1f}s)")
    conn.close()


# ── Stats ─────────────────────────────────────────────────────────────────────

def _print_stats(conn: sqlite3.Connection) -> None:
    n_nodes = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    n_edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    print(f"\n  DB stats: {n_nodes:,} nodes, {n_edges:,} edges")
    for kind, cnt in conn.execute(
        "SELECT kind, COUNT(*) FROM edges GROUP BY kind ORDER BY COUNT(*) DESC"
    ):
        print(f"    {kind:<12} {cnt:>10,}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dot",     required=True, type=Path, help="Path to unified_graph.dot")
    parser.add_argument("--nodes",   required=True, type=Path, help="Path to unified_graph_nodes.csv")
    parser.add_argument("--db",      required=True, type=Path, help="Output SQLite DB path")
    parser.add_argument("--project", default="Unknown",        help="Project name for global-db mode")
    parser.add_argument("--global-db", action="store_true",
                        help="Merge into existing global_corpus.db instead of fresh schema")
    args = parser.parse_args()

    if not args.dot.exists():
        print(f"Error: DOT file not found: {args.dot}", file=sys.stderr)
        sys.exit(1)

    t0 = time.time()
    if args.global_db:
        print(f"Merging into global corpus: {args.db}")
        ingest_global(args.dot, args.nodes, args.db, args.project)
    else:
        print(f"Writing fresh DB: {args.db}")
        ingest_fresh(args.dot, args.nodes, args.db)

    print(f"\nTotal: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
