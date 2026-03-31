from __future__ import annotations

import sys
import os
import argparse
from pathlib import Path
from loguru import logger

# Ensure project root is in path for module imports
sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), "formalized_graph"))

from ingestion.factory import GroundTruthFactory


def run_global_ingestion(task_id: int = 0, total_tasks: int = 1, limit: int | None = None):
    """
    The master runner for the Verified Lean Corpus.
    When total_tasks > 1, only processes this task's slice of files (for SLURM array jobs).
    When limit is set, only processes the first N files (for test runs).
    """
    logger.info(f"🚀 Starting Extraction — task {task_id}/{total_tasks}" + (f" (limit {limit})" if limit else ""))

    repo_root = Path(__file__).parent.parent
    db_path = repo_root / "data" / "generated" / "global_corpus.db"
    mathlib_path = repo_root / "data" / "mathlib" / "mathlib4"

    factory = GroundTruthFactory(db_path=db_path)

    if mathlib_path.exists():
        factory.process_project(
            mathlib_path, "Mathlib", is_mathlib=True,
            task_id=task_id, total_tasks=total_tasks,
            limit=limit,
        )
    else:
        logger.warning(f"Mathlib not found at {mathlib_path}.")

    stats = factory.db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    logger.success(f"✅ Done. Total nodes in corpus: {stats}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--task-id", type=int,
        default=int(os.environ.get("SLURM_ARRAY_TASK_ID", 0)),
        help="SLURM array task index (0-based). Defaults to $SLURM_ARRAY_TASK_ID.",
    )
    parser.add_argument(
        "--total-tasks", type=int, default=1,
        help="Total number of SLURM array tasks. 1 = run all files (local).",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Only process the first N files. Useful for test runs.",
    )
    args = parser.parse_args()

    try:
        run_global_ingestion(task_id=args.task_id, total_tasks=args.total_tasks, limit=args.limit)
    except KeyboardInterrupt:
        logger.warning("Interrupted.")
    except Exception as e:
        logger.critical(f"Failed: {e}")
