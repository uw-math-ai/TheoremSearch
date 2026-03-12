from __future__ import annotations

import sys
import os
from pathlib import Path
from loguru import logger

# Ensure project root is in path
sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), "formalized_graph"))

from ingestion.factory import GroundTruthFactory

def run_reingestion():
    """Manually re-ingests all existing *.ast.json files into the corpus."""
    db_path = Path("formalized_graph/data/generated/global_corpus.db")
    factory = GroundTruthFactory(db_path=db_path)
    
    mathlib_path = Path("formalized_graph/data/mathlib/mathlib4")
    logger.info(f"Searching for existing AST files in {mathlib_path}")
    
    ast_files = list(mathlib_path.rglob("*.ast.json"))
    logger.info(f"Found {len(ast_files)} files ready for ingestion.")
    
    if not ast_files:
        logger.error("No AST files found. Ingestion cannot proceed.")
        return

    # Add/Get Project ID
    project_id = factory.db.add_project("Mathlib", is_mathlib=True)
    
    # Run the robust ingestion logic
    factory._ingest_ast_files(ast_files, project_id, mathlib_path)
    
    # Check stats
    cursor = factory.db.conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM nodes")
    count = cursor.fetchone()[0]
    logger.success(f"Recovery complete. Total nodes now in DB: {count}")

if __name__ == "__main__":
    run_reingestion()
