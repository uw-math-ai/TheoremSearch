#!/usr/bin/env python3
"""
Smoke-test the lean-graph wiring without running a full Lean build.
Checks that:
  1. lean-graph source is present and the Cli version is pinned correctly
  2. setup_unified_extractor.py correctly patches a target lakefile
  3. The DOT parser and DB ingestion produce sensible output from a
     synthetic mini-DOT file

Run this locally (no Lean installation required).
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
LEAN_GRAPH = REPO_ROOT / "formalized_graph" / "lean-graph"


def check_lean_graph_source() -> None:
    print("1. Checking lean-graph source...")
    assert LEAN_GRAPH.exists(), f"Missing: {LEAN_GRAPH}"

    toml = (LEAN_GRAPH / "lakefile.toml").read_text()
    assert 'name = "importGraph"' in toml, "Package name wrong"
    assert 'rev = "v4.28.0"' in toml, f"Cli not pinned to v4.28.0:\n{toml}"

    toolchain = (LEAN_GRAPH / "lean-toolchain").read_text().strip()
    assert toolchain == "leanprover/lean4:v4.28.0", f"Toolchain mismatch: {toolchain}"

    key_files = [
        "ImportGraph/Graph/Unified.lean",
        "ImportGraph/Graph/ProofDeps.lean",
        "ImportGraph/Graph/TypeDeps.lean",
        "ImportGraph/Graph/Structures.lean",
        "ImportGraph/Graph/FilterCommon.lean",
    ]
    for f in key_files:
        assert (LEAN_GRAPH / f).exists(), f"Missing source: {f}"

    print("   PASS — lean-graph source OK, toolchain and Cli pinned to v4.28.0")


def check_lakefile_patch() -> None:
    print("2. Checking lakefile patching logic...")
    import sys
    sys.path.insert(0, str(REPO_ROOT / "formalized_graph" / "scripts"))
    from setup_unified_extractor import patch_lakefile_toml

    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)

        # Simulate sphere-eversion's lakefile.toml (has inherited importGraph)
        (project / "lakefile.toml").write_text(
            'name = "SphereEversion"\n\n'
            '[[require]]\nname = "mathlib"\nscope = "leanprover-community"\n\n'
            '[[require]]\nname = "importGraph"\ngit = "https://github.com/..."\nrev = "abc123"\n\n'
            '[[lean_lib]]\nname = "SphereEversion"\n'
        )

        fake_lean_graph = Path("/fake/lean-graph")
        patched = patch_lakefile_toml(project, fake_lean_graph)
        assert patched, "Should have patched"

        content = (project / "lakefile.toml").read_text()
        assert '/fake/lean-graph' in content, "Path not injected"
        assert content.count('name = "importGraph"') == 1, "Duplicate importGraph require"

        # Second call should be idempotent
        patched2 = patch_lakefile_toml(project, fake_lean_graph)
        assert not patched2, "Should not re-patch"

    print("   PASS — lakefile patching idempotent and correct")


def check_dot_ingest() -> None:
    print("3. Checking DOT parsing and DB ingestion...")
    import sys
    sys.path.insert(0, str(REPO_ROOT / "formalized_graph" / "scripts"))
    from ingest_unified_dot import stream_edges, load_nodes_csv, ingest_fresh

    mini_dot = (
        'digraph {\n'
        '  "Mathlib.A.foo" -> "Mathlib.A.bar" [kind=proof, color=green];\n'
        '  "Mathlib.A.baz" -> "Mathlib.A.foo" [kind=sig, color=orange];\n'
        '  "SphereEversion.X.thm1" -> "Mathlib.A.foo" [kind=proof, color=green];\n'
        '  "SphereEversion.X.thm1" -> "Mathlib.A.baz" [kind=signature, color=orange];\n'
        '}\n'
    )
    mini_nodes = (
        '"name","decl_type","module"\n'
        '"Mathlib.A.foo","thm","Mathlib.A"\n'
        '"Mathlib.A.bar","def","Mathlib.A"\n'
        '"Mathlib.A.baz","thm","Mathlib.A"\n'
        '"SphereEversion.X.thm1","thm","SphereEversion.X"\n'
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        dot_path = d / "test.dot"
        nodes_path = d / "test_nodes.csv"
        db_path = d / "test.db"

        dot_path.write_text(mini_dot)
        nodes_path.write_text(mini_nodes)

        edges = list(stream_edges(dot_path))
        assert len(edges) == 4, f"Expected 4 edges, got {len(edges)}"
        # DOT uses "sig" label; KIND_MAP should normalise to "signature"
        kinds = {e[2] for e in edges}
        assert "proof" in kinds, "proof edges missing"
        assert "signature" in kinds, f"signature normalisation failed; got {kinds}"

        nodes = load_nodes_csv(nodes_path)
        assert len(nodes) == 4, f"Expected 4 nodes, got {len(nodes)}"

        ingest_fresh(dot_path, nodes_path, db_path)
        conn = sqlite3.connect(str(db_path))
        n = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        e = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        assert n == 4, f"DB node count wrong: {n}"
        assert e == 4, f"DB edge count wrong: {e}"
        kinds_db = {r[0] for r in conn.execute("SELECT DISTINCT kind FROM edges")}
        assert "proof" in kinds_db
        assert "signature" in kinds_db
        conn.close()

    print("   PASS — DOT parsing, normalisation, and DB ingestion correct")


def main() -> None:
    print(f"Smoke-testing lean-graph integration in {REPO_ROOT}\n")
    check_lean_graph_source()
    check_lakefile_patch()
    check_dot_ingest()
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
