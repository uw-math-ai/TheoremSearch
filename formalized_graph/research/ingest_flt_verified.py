from __future__ import annotations

import sys
import os
from pathlib import Path
from loguru import logger

# Ensure project root is in path
sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), "formalized_graph"))

from ingestion.factory import GroundTruthFactory
from ingestion.rebuild import rebuild_database

def run_flt_ingestion():
    """Manually ingests the finished FLT trace into the verified corpus."""
    db_path = Path("formalized_graph/data/generated/global_corpus.db")
    factory = GroundTruthFactory(db_path=db_path)
    
    flt_root = Path("formalized_graph/data/formalization_projects/FLT")
    logger.info(f"Searching for verified FLT trace artifacts in {flt_root}")
    
    ast_files = list(flt_root.rglob("*.ast.json"))
    logger.info(f"Found {len(ast_files)} FLT files ready for verified ingestion.")
    
    if not ast_files:
        logger.error("No AST files found for FLT. Did extraction truly finish?")
        return

    # 1. Ingest Nodes
    project_id = factory.db.add_project("FLT", is_mathlib=False)
    factory._ingest_ast_files(ast_files, project_id, flt_root)
    
    # 2. Resolve Edges (linking FLT to Mathlib)
    logger.info("Resolving logical edges (FLT -> Mathlib) using Fast Rebuild...")
    rebuild_database()
    
    # Check stats
    cursor = factory.db.conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM nodes WHERE project_id = ?", (project_id,))
    count = cursor.fetchone()[0]
    logger.success(f"FLT Ingestion complete. Total FLT nodes: {count}")

if __name__ == "__main__":
    run_flt_ingestion()
