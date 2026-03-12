from __future__ import annotations

import sys
import os
from pathlib import Path
from loguru import logger

# Ensure project root is in path for module imports
sys.path.append(os.getcwd())

# Add the formalized_graph directory to sys.path to allow local module imports
sys.path.append(os.path.join(os.getcwd(), "formalized_graph"))

from ingestion.factory import GroundTruthFactory

def run_global_ingestion():
    """
    The master runner for the Verified Lean Corpus.
    This script builds the global SQLite database from up-to-date source code.
    """
    logger.info("🚀 Starting Global Verified Corpus Ingestion")
    
    # 1. Setup Paths
    db_path = Path("formalized_graph/data/generated/global_corpus.db")
    mathlib_path = Path("formalized_graph/data/mathlib/mathlib4")
    projects_dir = Path("formalized_graph/data/formalization_projects")
    
    # 2. Initialize the Factory
    factory = GroundTruthFactory(db_path=db_path)
    
    # 3. Step 1: Ingest Mathlib (The Base Layer)
    if mathlib_path.exists():
        logger.info("Found Mathlib. Beginning parallel extraction...")
        factory.process_project(mathlib_path, "Mathlib", is_mathlib=True)
    else:
        logger.warning(f"Mathlib not found at {mathlib_path}. Skipping base layer.")

    # 4. Step 2: Auto-Discover and Ingest Formalization Projects
    if projects_dir.exists():
        for project_dir in projects_dir.iterdir():
            if project_dir.is_dir() and project_dir.name != "Mathlib":
                logger.info(f"Ingesting project: {project_dir.name}")
                factory.process_project(project_dir, project_dir.name, is_mathlib=False)
    
    # 5. Final Statistics
    stats = factory.db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    logger.success(f"✅ Ingestion Complete! Total verified nodes in corpus: {stats}")
    logger.info(f"Database location: {db_path.absolute()}")

if __name__ == "__main__":
    try:
        run_global_ingestion()
    except KeyboardInterrupt:
        logger.warning("\nIngestion interrupted by user.")
    except Exception as e:
        logger.critical(f"Ingestion failed with critical error: {e}")
