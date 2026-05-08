"""
Ingest lean-graph NDJSON + export_statements JSONL into corpus_v2.db.

Usage:
    # Ingest a single project:
    python3 -m ingestion.ingest_ndjson \
        --graph data/generated/ndjson/mathlib.ndjson \
        --statements data/generated/ndjson/mathlib_statements.jsonl \
        --project Mathlib \
        --url https://github.com/leanprover-community/mathlib4 \
        --toolchain v4.29.0 \
        --git-commit abc123

    # Ingest without statements (edges + basic nodes only):
    python3 -m ingestion.ingest_ndjson \
        --graph data/generated/ndjson/pfr.ndjson \
        --project pfr
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .database_v2 import CorpusV2, VALID_EDGE_TYPES

# Default DB location
DEFAULT_DB = Path(__file__).parent.parent / "data" / "generated" / "corpus_v2.db"


def module_to_filepath(module: str) -> str:
    """Mathlib.Algebra.Group.Defs → Mathlib/Algebra/Group/Defs.lean"""
    return module.replace(".", "/") + ".lean"


def load_statements(path: Path) -> dict[str, dict]:
    """Load export_statements JSONL into {name → {signature, docstring, ...}}."""
    stmts: dict[str, dict] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            stmts[obj["name"]] = obj
    return stmts


def ingest_project(
    db: CorpusV2,
    graph_path: Path,
    statements_path: Path | None,
    project_name: str,
    url: str | None = None,
    toolchain: str | None = None,
    mathlib_rev: str | None = None,
    commit: str | None = None,
):
    """Ingest one project's lean-graph output into the database."""

    # Load statements if available
    stmts: dict[str, dict] = {}
    if statements_path and statements_path.exists():
        print(f"Loading statements from {statements_path}...")
        stmts = load_statements(statements_path)
        print(f"  {len(stmts)} statements loaded")

    # Register project
    project_id = db.add_project(
        name=project_name,
        url=url,
        lean_toolchain=toolchain,
        mathlib_rev=mathlib_rev,
        git_commit=commit,
    )

    # Pass 1: Read NDJSON, collect nodes and raw edges
    print(f"Reading graph from {graph_path}...")
    nodes: dict[str, dict] = {}   # name → {kind, module}
    raw_edges: list[tuple[str, str, str]] = []  # (source_name, target_name, edge_type)

    with open(graph_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            name = obj["name"]
            kind = obj.get("decl_type", "unknown")
            module = obj.get("module", "")

            nodes[name] = {"kind": kind, "module": module}

            for edge in obj.get("edges", []):
                target = edge["target"]
                edge_type = edge["kind"]
                if edge_type not in VALID_EDGE_TYPES:
                    continue
                raw_edges.append((name, target, edge_type))
                # Ensure target exists as a node (may come from outside this project)
                if target not in nodes:
                    nodes[target] = {"kind": "unknown", "module": ""}

    print(f"  {len(nodes)} nodes, {len(raw_edges)} edges")

    # Pass 2: Insert nodes with statement data joined in
    print("Inserting nodes...")
    node_rows = []
    for name, info in nodes.items():
        stmt = stmts.get(name, {})
        module = stmt.get("module", info["module"])
        kind = stmt.get("decl_type", info["kind"])
        signature = stmt.get("signature", "")
        docstring = stmt.get("docstring", "")
        file_path = module_to_filepath(module) if module else ""

        node_rows.append((
            project_id, name, kind, module, file_path, signature, docstring
        ))

    CHUNK = 10_000
    total_inserted = 0
    for i in range(0, len(node_rows), CHUNK):
        total_inserted += db.bulk_insert_nodes(node_rows[i:i + CHUNK])
    print(f"  {total_inserted} new nodes inserted ({len(node_rows)} total, rest already existed)")

    # Pass 3: Resolve edges (name → id) and insert
    print("Resolving edges...")
    name_to_id = db.get_name_to_id()

    edge_rows = []
    unresolved = 0
    for src_name, tgt_name, edge_type in raw_edges:
        src_id = name_to_id.get(src_name)
        tgt_id = name_to_id.get(tgt_name)
        if src_id is None or tgt_id is None:
            unresolved += 1
            continue
        edge_rows.append((src_id, tgt_id, edge_type))

    total_edges = 0
    for i in range(0, len(edge_rows), CHUNK):
        total_edges += db.bulk_insert_edges(edge_rows[i:i + CHUNK])
    print(f"  {total_edges} edges inserted ({unresolved} unresolved targets skipped)")

    # Summary
    stats = db.get_stats()
    print(f"\nDB totals: {stats['nodes']} nodes, {stats['edges']} edges, {stats['projects']} projects")
    print(f"Edge types: {stats['edge_types']}")
    print(f"Kinds: {stats['kinds']}")


def main():
    parser = argparse.ArgumentParser(description="Ingest lean-graph NDJSON into corpus_v2.db")
    parser.add_argument("--graph", type=Path, required=True, help="Path to .ndjson from lean-graph")
    parser.add_argument("--statements", type=Path, default=None, help="Path to .jsonl from export_statements")
    parser.add_argument("--project", type=str, required=True, help="Project name")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Database path")
    parser.add_argument("--url", type=str, default=None)
    parser.add_argument("--toolchain", type=str, default=None)
    parser.add_argument("--mathlib-rev", type=str, default=None)
    parser.add_argument("--git-commit", type=str, default=None)
    args = parser.parse_args()

    db = CorpusV2(args.db)
    try:
        ingest_project(
            db=db,
            graph_path=args.graph,
            statements_path=args.statements,
            project_name=args.project,
            url=args.url,
            toolchain=args.toolchain,
            mathlib_rev=args.mathlib_rev,
            git_commit=args.git_commit,
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
