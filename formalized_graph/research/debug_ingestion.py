from __future__ import annotations

import sys
import os
import subprocess
from pathlib import Path
from loguru import logger

# Ensure project root is in path
sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), "formalized_graph"))

from ingestion.factory import GroundTruthFactory

LAKE_PATH = "/Users/simon/.elan/bin/lake"

def debug_small_subset():
    """Tries to ingest 5 files synchronously to find the error."""
    db_file = Path("formalized_graph/data/generated/debug_corpus.db")
    if db_file.exists(): os.remove(db_file)
    
    factory = GroundTruthFactory(db_path=db_file)
    mathlib_path = Path("formalized_graph/data/mathlib/mathlib4")
    
    # 1. Manually find 5 files
    lean_files = list(mathlib_path.rglob("Mathlib/Data/*.lean"))[:5]
    logger.info(f"Debugging with {len(lean_files)} files.")

    temp_extractor = mathlib_path / "ExtractData.lean"
    temp_extractor.write_text(factory.extractor_lean.read_text())

    for f in lean_files:
        if f.name == "ExtractData.lean": continue
        # Make path relative to mathlib_path
        rel_f = f.relative_to(mathlib_path)
        logger.info(f"Processing: {rel_f}")
        cmd = [LAKE_PATH, "env", "lean", "--run", "ExtractData.lean", str(rel_f)]
        try:
            subprocess.run(cmd, cwd=mathlib_path, capture_output=True, text=True, check=True)
            logger.success(f"Success: {rel_f}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed: {rel_f}")
            print(f"STDERR: {e.stderr}")
            break
        except Exception as e:
            logger.critical(f"Error: {e}")
            break
    
    if temp_extractor.exists(): os.remove(temp_extractor)

if __name__ == "__main__":
    debug_small_subset()
