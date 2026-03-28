from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class CorpusDatabase:
    """
    Manages the persistent global mathematical corpus.
    Built for local SQLite, extensible to cloud RDS (PostgreSQL).
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        cursor = self.conn.cursor()

        # Projects: Repositories in the corpus
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                url TEXT,
                is_mathlib BOOLEAN NOT NULL DEFAULT 0,
                ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        # Nodes: Verified theorems, definitions, lemmas
        # GUID is 'full_name'. This is the primary key for mathematical identity.
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                full_name TEXT UNIQUE NOT NULL,
                kind TEXT NOT NULL,
                file_path TEXT,
                docstring TEXT,
                statement TEXT,
                in_degree INTEGER NOT NULL DEFAULT 0,
                out_degree INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(project_id) REFERENCES projects(id)
            )
        """
        )

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(full_name)")

        # Edges: Verified dependencies
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS edges (
                source_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL,
                is_implicit BOOLEAN NOT NULL DEFAULT 0,
                tactic_context TEXT,
                PRIMARY KEY (source_id, target_id),
                FOREIGN KEY(source_id) REFERENCES nodes(id),
                FOREIGN KEY(target_id) REFERENCES nodes(id)
            )
        """
        )

        self.conn.commit()

    def add_project(
        self, name: str, url: str | None = None, is_mathlib: bool = False
    ) -> int:
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO projects (name, url, is_mathlib) VALUES (?, ?, ?)",
            (name, url, is_mathlib),
        )
        self.conn.commit()
        cursor.execute("SELECT id FROM projects WHERE name = ?", (name,))
        res = cursor.fetchone()
        if res is None:
            raise ValueError(f"Project {name} could not be found or added.")
        return int(res["id"])

    def bulk_insert_nodes(self, node_tuples: list[tuple[Any, ...]]) -> None:
        """High-performance bulk insert for verified premises."""
        cursor = self.conn.cursor()
        cursor.executemany(
            """
            INSERT OR IGNORE INTO nodes (project_id, full_name, kind, file_path, docstring, statement)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            node_tuples,
        )
        self.conn.commit()

    def bulk_insert_edges(self, edge_tuples: list[tuple[Any, ...]]) -> None:
        """High-performance bulk insert for verified dependencies."""
        cursor = self.conn.cursor()
        cursor.executemany(
            """
            INSERT OR IGNORE INTO edges (source_id, target_id, is_implicit, tactic_context)
            VALUES (?, ?, ?, ?)
        """,
            edge_tuples,
        )
        self.conn.commit()

    def get_id_map(self) -> dict[str, int]:
        """Returns a mapping of full_name to internal DB ID for fast edge resolution."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, full_name FROM nodes")
        return {row["full_name"]: row["id"] for row in cursor.fetchall()}

    def close(self) -> None:
        self.conn.close()
