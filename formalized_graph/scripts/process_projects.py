"""
Multi-project extraction orchestrator.

Clones, builds, and extracts Lean 4 formalization projects into the
unified corpus DB. Tracks per-project git state in a manifest so
re-runs skip unchanged repos and log exactly what was processed.

Usage:
    # Process all enabled projects:
    python3 formalized_graph/scripts/process_projects.py

    # Process a single project by name:
    python3 formalized_graph/scripts/process_projects.py --project pfr

    # Clone/pull only (no build or extract):
    python3 formalized_graph/scripts/process_projects.py --clone-only

    # Skip lake build (extract from existing .olean):
    python3 formalized_graph/scripts/process_projects.py --skip-build

    # Force re-extract even if commit unchanged:
    python3 formalized_graph/scripts/process_projects.py --force
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), "formalized_graph"))

from ingestion.factory import GroundTruthFactory


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent
REGISTRY_PATH = REPO_ROOT / "projects.json"
PROJECTS_DIR = REPO_ROOT / "data" / "formalization_projects"
MANIFEST_PATH = REPO_ROOT / "data" / "generated" / "project_manifest.json"
DB_PATH = REPO_ROOT / "data" / "generated" / "global_corpus.db"


# ---------------------------------------------------------------------------
# Manifest helpers — tracks per-project git state across runs
# ---------------------------------------------------------------------------
def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {}


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------
def git_clone(url: str, dest: Path) -> None:
    logger.info(f"Cloning {url} → {dest}")
    subprocess.run(
        ["git", "clone", "--depth=1", url, str(dest)],
        check=True,
    )


def git_pull(repo: Path) -> None:
    logger.info(f"Pulling latest in {repo}")
    subprocess.run(["git", "pull", "--ff-only"], cwd=repo, check=True)


def git_info(repo: Path) -> dict:
    """Return commit hash, date, and branch for a repo."""
    def _run(args):
        r = subprocess.run(
            ["git"] + args, cwd=repo,
            capture_output=True, text=True, check=True,
        )
        return r.stdout.strip()

    return {
        "commit": _run(["rev-parse", "HEAD"]),
        "commit_date": _run(["log", "-1", "--format=%aI"]),
        "branch": _run(["rev-parse", "--abbrev-ref", "HEAD"]),
    }


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def lake_build(project_path: Path, timeout: int = 7200) -> None:
    """Run `lake build` in the project directory."""
    lake = os.environ.get("LAKE_BIN") or str(Path.home() / ".elan" / "bin" / "lake")
    logger.info(f"Running lake build in {project_path} (timeout={timeout}s)")
    subprocess.run(
        [lake, "build"],
        cwd=project_path,
        timeout=timeout,
        check=True,
    )


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------
def extract_project(
    project_path: Path,
    project_name: str,
    timeout: int = 600,
    retry_missing: bool = False,
) -> dict:
    """Run the extraction pipeline on a single project. Returns stats."""
    factory = GroundTruthFactory(db_path=DB_PATH)
    factory.process_project(
        project_path,
        project_name,
        is_mathlib=False,
        retry_missing=retry_missing,
        timeout=timeout,
    )

    # Count files extracted
    build_ir = project_path / ".lake" / "build" / "ir"
    ast_count = len(list(build_ir.rglob("*.ast.json"))) if build_ir.exists() else 0
    lean_count = sum(
        1 for f in project_path.rglob("*.lean")
        if ".lake" not in str(f) and f.name != "ExtractData.lean"
    )
    return {"files_total": lean_count, "files_extracted": ast_count}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def process_one(
    entry: dict,
    manifest: dict,
    *,
    clone_only: bool = False,
    skip_build: bool = False,
    force: bool = False,
    timeout: int = 600,
) -> None:
    name = entry["name"]
    url = entry["url"]
    project_path = PROJECTS_DIR / name

    # 1. Clone or pull
    if not project_path.exists():
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        git_clone(url, project_path)
    else:
        try:
            git_pull(project_path)
        except subprocess.CalledProcessError:
            logger.warning(f"git pull failed for {name}, continuing with existing state")

    # 2. Record git state
    info = git_info(project_path)
    prev = manifest.get(name, {})
    logger.info(
        f"{name}: commit={info['commit'][:10]} "
        f"date={info['commit_date']} branch={info['branch']}"
    )

    if clone_only:
        manifest[name] = {**prev, **info, "last_synced": _now()}
        return

    # 3. Skip if commit unchanged (unless --force)
    if not force and prev.get("commit") == info["commit"]:
        logger.info(f"{name}: commit unchanged, skipping (use --force to override)")
        return

    # 4. Build
    if not skip_build:
        try:
            lake_build(project_path)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.error(f"{name}: lake build failed: {e}")
            manifest[name] = {
                **info,
                "last_attempted": _now(),
                "status": "build_failed",
                "error": str(e)[:200],
            }
            return

    # 5. Extract
    try:
        stats = extract_project(project_path, name, timeout=timeout)
        manifest[name] = {
            **info,
            **stats,
            "last_extracted": _now(),
            "status": "complete",
        }
        logger.success(
            f"{name}: {stats['files_extracted']}/{stats['files_total']} files extracted"
        )
    except Exception as e:
        logger.error(f"{name}: extraction failed: {e}")
        manifest[name] = {
            **info,
            "last_attempted": _now(),
            "status": "extract_failed",
            "error": str(e)[:200],
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main():
    parser = argparse.ArgumentParser(description="Process Lean formalization projects")
    parser.add_argument("--project", type=str, help="Process a single project by name")
    parser.add_argument("--clone-only", action="store_true", help="Clone/pull repos without building or extracting")
    parser.add_argument("--skip-build", action="store_true", help="Skip lake build, extract from existing .olean files")
    parser.add_argument("--force", action="store_true", help="Re-extract even if commit is unchanged")
    parser.add_argument("--timeout", type=int, default=600, help="Per-file extraction timeout in seconds")
    args = parser.parse_args()

    registry = json.loads(REGISTRY_PATH.read_text())
    manifest = load_manifest()

    if args.project:
        entries = [e for e in registry if e["name"] == args.project]
        if not entries:
            logger.error(f"Project '{args.project}' not found in registry")
            sys.exit(1)
    else:
        entries = registry

    logger.info(f"Processing {len(entries)} project(s)")

    for entry in entries:
        try:
            process_one(
                entry, manifest,
                clone_only=args.clone_only,
                skip_build=args.skip_build,
                force=args.force,
                timeout=args.timeout,
            )
        except Exception as e:
            logger.error(f"Unexpected error processing {entry['name']}: {e}")
        finally:
            save_manifest(manifest)

    # Summary
    logger.info("=== Manifest Summary ===")
    for name, info in sorted(manifest.items()):
        status = info.get("status", "unknown")
        commit = info.get("commit", "?")[:10]
        extracted = info.get("files_extracted", "?")
        total = info.get("files_total", "?")
        logger.info(f"  {name:30s}  {status:15s}  {commit}  {extracted}/{total} files")


if __name__ == "__main__":
    main()
