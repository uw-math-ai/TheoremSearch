"""
Ingest lean-graph NDJSON + export_statements JSONL into the corpus db.

Single project:
    python3 -m ingestion.ingest \
        --graph /path/to/Mathlib_v429.ndjson \
        --statements /path/to/Mathlib_v429_statements.jsonl \
        --project Mathlib_v429 \
        --toolchain v4.29.0

Batch (scan a directory for matching .ndjson + _statements.jsonl pairs):
    python3 -m ingestion.ingest --all /path/to/out/projects/

Adapted from simku22's corpus_v2 ingest pipeline.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .database import Corpus, VALID_EDGE_TYPES

DEFAULT_DB = Path(__file__).parent.parent / "data" / "corpus_v3.db"


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
    db: Corpus,
    graph_path: Path,
    statements_path: Path | None,
    project_name: str,
    url: str | None = None,
    toolchain: str | None = None,
    mathlib_rev: str | None = None,
    git_commit: str | None = None,
    lean_graph_commit: str | None = None,
):
    stmts: dict[str, dict] = {}
    if statements_path and statements_path.exists():
        print(f"  loading statements from {statements_path.name}")
        stmts = load_statements(statements_path)
        print(f"    {len(stmts)} statements")

    project_id = db.add_project(
        name=project_name,
        url=url,
        lean_toolchain=toolchain,
        mathlib_rev=mathlib_rev,
        git_commit=git_commit,
        lean_graph_commit=lean_graph_commit,
    )

    print(f"  reading graph from {graph_path.name}")
    nodes: dict[str, dict] = {}
    raw_edges: list[tuple[str, str, str]] = []

    with open(graph_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            name = obj["name"]
            kind = obj.get("decl_type", "unknown")
            module = obj.get("module", "")
            is_instance = bool(obj.get("is_instance", False))

            nodes[name] = {"kind": kind, "module": module, "is_instance": is_instance}

            for edge in obj.get("edges", []):
                target = edge["target"]
                edge_type = edge["kind"]
                if edge_type not in VALID_EDGE_TYPES:
                    continue
                # sig edges carry position/binder/role/via_proj; other kinds don't.
                via = edge.get("via_proj")
                raw_edges.append((
                    name, target, edge_type,
                    edge.get("position"),
                    edge.get("binder"),
                    edge.get("role"),
                    None if via is None else (1 if via else 0),
                ))
                # Target may live in a dep package outside this project's
                # NDJSON — stub it in so edges can resolve.
                if target not in nodes:
                    nodes[target] = {"kind": "unknown", "module": "", "is_instance": False}

    print(f"    {len(nodes)} nodes, {len(raw_edges)} edges")

    node_rows = []
    for name, info in nodes.items():
        stmt = stmts.get(name, {})
        module = stmt.get("module", info["module"])
        kind = stmt.get("decl_type", info["kind"])
        signature = stmt.get("signature", "")
        docstring = stmt.get("docstring", "")
        file_path = module_to_filepath(module) if module else ""
        is_instance = 1 if info.get("is_instance") else 0
        node_rows.append((
            project_id, name, kind, module, file_path, signature, docstring, is_instance
        ))

    CHUNK = 10_000
    inserted = 0
    for i in range(0, len(node_rows), CHUNK):
        inserted += db.bulk_insert_nodes(node_rows[i:i + CHUNK])
    print(f"    {inserted} new nodes inserted ({len(node_rows) - inserted} already existed)")

    name_to_id = db.get_name_to_id()
    edge_rows = []
    unresolved = 0
    for src_name, tgt_name, edge_type, position, binder, role, via_proj in raw_edges:
        src_id = name_to_id.get(src_name)
        tgt_id = name_to_id.get(tgt_name)
        if src_id is None or tgt_id is None:
            unresolved += 1
            continue
        edge_rows.append((src_id, tgt_id, edge_type, position, binder, role, via_proj))

    total_edges = 0
    for i in range(0, len(edge_rows), CHUNK):
        total_edges += db.bulk_insert_edges(edge_rows[i:i + CHUNK])
    print(f"    {total_edges} new edges inserted ({unresolved} unresolved target names skipped)")


def find_pairs(directory: Path) -> list[tuple[str, Path, Path | None]]:
    """Find (project_name, ndjson_path, jsonl_path|None) tuples in directory.

    Project name is the .ndjson basename without extension; the matching
    JSONL is <name>_statements.jsonl (or None if not present).
    """
    pairs = []
    for ndjson in sorted(directory.glob("*.ndjson")):
        if ndjson.name.endswith("_statements.jsonl"):
            continue  # not a graph file
        name = ndjson.stem  # e.g. "Mathlib_v429" or "ClassFieldTheory"
        stmts = directory / f"{name}_statements.jsonl"
        pairs.append((name, ndjson, stmts if stmts.exists() else None))
    return pairs


def infer_toolchain(project_name: str) -> str | None:
    """Mathlib_v429 → v4.29.0. None if not encoded in the name."""
    m = re.match(r".*_v4(\d)(\d)$", project_name)
    if m:
        return f"v4.{m.group(1)}.{m.group(2)}" if m.group(2) != '0' else f"v4.{m.group(1)}.0"
    return None


def main():
    ap = argparse.ArgumentParser(description="Ingest lean-graph NDJSON into corpus_v3.db")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--all", type=Path, default=None,
                    help="Batch mode: directory containing *.ndjson + *_statements.jsonl pairs")
    ap.add_argument("--graph", type=Path, default=None)
    ap.add_argument("--statements", type=Path, default=None)
    ap.add_argument("--project", type=str, default=None)
    ap.add_argument("--url", type=str, default=None)
    ap.add_argument("--toolchain", type=str, default=None)
    ap.add_argument("--mathlib-rev", type=str, default=None)
    ap.add_argument("--git-commit", type=str, default=None)
    ap.add_argument("--lean-graph-commit", type=str, default=None)
    args = ap.parse_args()

    if args.all:
        if not args.all.is_dir():
            print(f"--all: {args.all} is not a directory", file=sys.stderr)
            sys.exit(2)
        pairs = find_pairs(args.all)
        print(f"Found {len(pairs)} project(s) in {args.all}")
        db = Corpus(args.db)
        try:
            for name, ndjson, jsonl in pairs:
                print(f"\n=== {name} ===")
                ingest_project(
                    db=db,
                    graph_path=ndjson,
                    statements_path=jsonl,
                    project_name=name,
                    toolchain=infer_toolchain(name),
                    lean_graph_commit=args.lean_graph_commit,
                )
            stats = db.get_stats()
            print(f"\n=== final ===")
            print(f"  {stats['projects']} projects, {stats['nodes']} nodes, {stats['edges']} edges")
            print(f"  edge types: {stats['edge_types']}")
            print(f"  top kinds: {dict(list(stats['kinds'].items())[:10])}")
        finally:
            db.close()
        return

    # Single-project mode
    if not (args.graph and args.project):
        ap.error("either --all <dir> or both --graph + --project required")
    db = Corpus(args.db)
    try:
        ingest_project(
            db=db,
            graph_path=args.graph,
            statements_path=args.statements,
            project_name=args.project,
            url=args.url,
            toolchain=args.toolchain or infer_toolchain(args.project),
            mathlib_rev=args.mathlib_rev,
            git_commit=args.git_commit,
            lean_graph_commit=args.lean_graph_commit,
        )
        stats = db.get_stats()
        print(f"\nDB totals: {stats['projects']} projects, {stats['nodes']} nodes, {stats['edges']} edges")
    finally:
        db.close()


if __name__ == "__main__":
    main()
