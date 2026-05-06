"""
v2 corpus database — stores lean-graph output with typed edges.

Schema:
  projects  — source repositories (Mathlib, PFR, FLT, ...)
  nodes     — declarations (theorems, defs, structures, ...)
  edges     — typed dependencies (extends/field/sig/proof/def/docref)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


VALID_EDGE_TYPES = {"extends", "field", "sig", "proof", "def", "docref"}


class CorpusV2:

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        c = self.conn.cursor()

        c.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT UNIQUE NOT NULL,
                url             TEXT,
                kind            TEXT NOT NULL DEFAULT 'lean_repo',
                lean_toolchain  TEXT,
                mathlib_rev     TEXT,
                commit          TEXT,
                extracted_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS nodes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id  INTEGER NOT NULL REFERENCES projects(id),
                full_name   TEXT UNIQUE NOT NULL,
                kind        TEXT NOT NULL,
                module      TEXT,
                file_path   TEXT,
                signature   TEXT,
                docstring   TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS edges (
                source_id   INTEGER NOT NULL REFERENCES nodes(id),
                target_id   INTEGER NOT NULL REFERENCES nodes(id),
                edge_type   TEXT NOT NULL,
                PRIMARY KEY (source_id, target_id, edge_type)
            )
        """)

        c.execute("CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(full_name)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_nodes_module ON nodes(module)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(edge_type)")

        self.conn.commit()

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    def add_project(
        self,
        name: str,
        url: str | None = None,
        lean_toolchain: str | None = None,
        mathlib_rev: str | None = None,
        commit: str | None = None,
    ) -> int:
        c = self.conn.cursor()
        c.execute("""
            INSERT INTO projects (name, url, lean_toolchain, mathlib_rev, commit)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                url = COALESCE(excluded.url, projects.url),
                lean_toolchain = COALESCE(excluded.lean_toolchain, projects.lean_toolchain),
                mathlib_rev = COALESCE(excluded.mathlib_rev, projects.mathlib_rev),
                commit = COALESCE(excluded.commit, projects.commit),
                extracted_at = CURRENT_TIMESTAMP
        """, (name, url, lean_toolchain, mathlib_rev, commit))
        self.conn.commit()
        row = c.execute("SELECT id FROM projects WHERE name = ?", (name,)).fetchone()
        return row["id"]

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    def bulk_insert_nodes(self, rows: list[tuple]) -> int:
        """Insert (project_id, full_name, kind, module, file_path, signature, docstring).
        Returns number of rows inserted."""
        c = self.conn.cursor()
        c.executemany("""
            INSERT OR IGNORE INTO nodes
                (project_id, full_name, kind, module, file_path, signature, docstring)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, rows)
        self.conn.commit()
        return c.rowcount

    # ------------------------------------------------------------------
    # Edges
    # ------------------------------------------------------------------

    def bulk_insert_edges(self, rows: list[tuple]) -> int:
        """Insert (source_id, target_id, edge_type).
        Returns number of rows inserted."""
        c = self.conn.cursor()
        c.executemany("""
            INSERT OR IGNORE INTO edges (source_id, target_id, edge_type)
            VALUES (?, ?, ?)
        """, rows)
        self.conn.commit()
        return c.rowcount

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def get_name_to_id(self) -> dict[str, int]:
        """Returns full_name → node id mapping."""
        rows = self.conn.execute("SELECT full_name, id FROM nodes").fetchall()
        return {r["full_name"]: r["id"] for r in rows}

    def get_stats(self) -> dict:
        c = self.conn.cursor()
        nodes = c.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        edges = c.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        projects = c.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        edge_types = c.execute(
            "SELECT edge_type, COUNT(*) as cnt FROM edges GROUP BY edge_type ORDER BY cnt DESC"
        ).fetchall()
        kind_counts = c.execute(
            "SELECT kind, COUNT(*) as cnt FROM nodes GROUP BY kind ORDER BY cnt DESC"
        ).fetchall()
        return {
            "nodes": nodes,
            "edges": edges,
            "projects": projects,
            "edge_types": {r["edge_type"]: r["cnt"] for r in edge_types},
            "kinds": {r["kind"]: r["cnt"] for r in kind_counts},
        }

    def close(self):
        self.conn.close()
