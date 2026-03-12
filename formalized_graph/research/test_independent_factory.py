from __future__ import annotations

import sys
import os
import subprocess
import json
from pathlib import Path
from loguru import logger

# Ensure project root is in path
sys.path.append(os.getcwd())

LAKE_PATH = "/Users/simon/.elan/bin/lake"

def test_char_extraction():
    """
    Tests our independent factory on Mathlib/Data/Char.lean with full debugging.
    """
    mathlib_root = Path("formalized_graph/data/mathlib/mathlib4")
    target_file = Path("Mathlib/Data/Char.lean")
    
    logger.info(f"Testing extraction on: {target_file}")
    
    try:
        extractor_src = Path("formalized_graph/lean/ExtractData.lean")
        extractor_dest = mathlib_root / "ExtractData.lean"
        extractor_dest.write_text(extractor_src.read_text())
        
        # Build command: Use 'lake env lean --run'
        cmd = [LAKE_PATH, "env", "lean", "--run", "ExtractData.lean", str(target_file)]
        
        logger.info(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=mathlib_root, capture_output=True, text=True)
        
        print("\n--- STDOUT ---")
        print(result.stdout)
        print("\n--- STDERR ---")
        print(result.stderr)
        
        if result.returncode == 0:
            logger.success("Lean compiler finished successfully!")
            # Check for generated JSON in mathlib_root
            gen_files = list(mathlib_root.glob("**/Char.ast.json"))
            if gen_files:
                logger.success(f"Generated {len(gen_files)} verified data files.")
                for f in gen_files:
                    print(f"Result Path: {f}")
            else:
                logger.warning("No JSON files were generated.")
        else:
            logger.error(f"Lean compiler failed with code {result.returncode}")

    finally:
        if extractor_dest.exists():
            os.remove(extractor_dest)

if __name__ == "__main__":
    test_char_extraction()
