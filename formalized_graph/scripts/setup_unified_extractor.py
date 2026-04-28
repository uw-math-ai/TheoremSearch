#!/usr/bin/env python3
"""
Wire the local lean-graph fork into a project's lakefile, overriding the
inherited importGraph (which lacks unified mode), then build the `graph`
executable inside that project's environment.

Usage:
    python3 formalized_graph/scripts/setup_unified_extractor.py \
        /path/to/project [--force]

After running this, the project can produce a unified DOT graph with:
    cd /path/to/project
    lake exe graph --mode unified --to <ProjectModule> output.dot
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
LEAN_GRAPH_PATH = REPO_ROOT / "formalized_graph" / "lean-graph"


def _lake(cmd: list[str], cwd: Path, timeout: int = 600) -> None:
    import os
    import shutil
    lake = os.environ.get("LAKE_BIN") or shutil.which("lake") or str(Path.home() / ".elan" / "bin" / "lake")
    full = [lake] + cmd
    print(f"  $ {' '.join(str(x) for x in full)}")
    subprocess.run(full, cwd=cwd, check=True, timeout=timeout)


def patch_lakefile_toml(project_path: Path, lean_graph_abs: Path) -> bool:
    """
    Add (or replace) importGraph require in lakefile.toml with a path pointing
    to our local lean-graph fork. Returns True if file was modified.
    """
    toml_path = project_path / "lakefile.toml"
    if not toml_path.exists():
        return False

    content = toml_path.read_text()
    lean_graph_str = str(lean_graph_abs)
    marker = f'path = "{lean_graph_str}"'

    if marker in content:
        print(f"  lean-graph already wired into {toml_path.name}")
        return False

    # Build the new require block
    new_block = (
        f'\n# Unified graph extraction (overrides inherited importGraph)\n'
        f'[[require]]\nname = "importGraph"\npath = "{lean_graph_str}"\n'
    )

    # If there's already an importGraph require (from Mathlib inheritance or
    # a previous wire-in), replace it.  Otherwise just append.
    import re
    pattern = re.compile(
        r'(\[\[require\]\]\s*\n(?:.*\n)*?name\s*=\s*"importGraph"\s*\n(?:.*\n)*?)'
        r'(?=\[\[|\Z)',
        re.MULTILINE,
    )

    if pattern.search(content):
        content = pattern.sub(new_block.lstrip('\n') + '\n', content, count=1)
    else:
        content = content + new_block

    toml_path.write_text(content)
    print(f"  Patched {toml_path.name}")
    return True


def patch_lakefile_lean(project_path: Path, lean_graph_abs: Path) -> bool:
    """Same as above but for lakefile.lean syntax."""
    lean_path = project_path / "lakefile.lean"
    if not lean_path.exists():
        return False

    content = lean_path.read_text()
    lean_graph_str = str(lean_graph_abs)

    if lean_graph_str in content:
        print(f"  lean-graph already wired into {lean_path.name}")
        return False

    new_line = f'\nrequire importGraph from "{lean_graph_str}"\n'

    import re
    # Replace existing importGraph require line if present
    existing = re.compile(r'require\s+importGraph\s+from\s+[^\n]+\n')
    if existing.search(content):
        content = existing.sub(new_line.lstrip('\n'), content, count=1)
    else:
        content = content + new_line

    lean_path.write_text(content)
    print(f"  Patched {lean_path.name}")
    return True


def setup(project_path: Path, force: bool = False) -> None:
    if not project_path.exists():
        print(f"Error: project not found at {project_path}", file=sys.stderr)
        sys.exit(1)

    if not LEAN_GRAPH_PATH.exists():
        print(f"Error: lean-graph not found at {LEAN_GRAPH_PATH}", file=sys.stderr)
        sys.exit(1)

    lean_graph_abs = LEAN_GRAPH_PATH.resolve()
    print(f"Setting up unified extractor for: {project_path.name}")
    print(f"  lean-graph source: {lean_graph_abs}")

    # 1. Patch the lakefile
    has_toml = (project_path / "lakefile.toml").exists()
    patched = False
    if has_toml:
        patched = patch_lakefile_toml(project_path, lean_graph_abs)
    else:
        patched = patch_lakefile_lean(project_path, lean_graph_abs)

    sentinel = project_path / ".lean_graph_setup_done"
    if not force and sentinel.exists() and not patched:
        print("  Setup already complete (use --force to redo).")
        return

    # 2. lake update importGraph (resolves the new dep into lake-manifest.json)
    print("  Running lake update importGraph...")
    _lake(["update", "importGraph"], cwd=project_path, timeout=120)

    # 3. Build the ImportGraph library
    print("  Building ImportGraph library (this takes ~1-2 min)...")
    _lake(["build", "ImportGraph"], cwd=project_path, timeout=600)

    # 4. Build the `graph` executable
    print("  Building graph executable...")
    _lake(["build", "graph"], cwd=project_path, timeout=600)

    sentinel.touch()
    print(f"\n  Done. Run extraction with:")
    print(f"    cd {project_path}")
    print(f"    lake exe graph --mode unified --to <Module> output.dot")


def main() -> None:
    parser = argparse.ArgumentParser(description="Wire lean-graph into a Lean project")
    parser.add_argument("project_path", type=Path, help="Path to the Lean project root")
    parser.add_argument("--force", action="store_true", help="Re-run even if already done")
    args = parser.parse_args()
    setup(args.project_path.resolve(), force=args.force)


if __name__ == "__main__":
    main()
