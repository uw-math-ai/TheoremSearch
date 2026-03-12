from __future__ import annotations

import sys
import os
from pathlib import Path

# Ensure project root is in path
sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), "formalized_graph"))

from ingestion.ingestor import GroundTruthIngestor
from ingestion.models import EntityKind
from loguru import logger

def run_pi_pos_comparison():
    """
    Simulates the ingestion of verified data for Real.pi_pos
    to demonstrate the difference between heuristic and ground truth.
    """
    logger.info("Starting Ground Truth Mock Ingestion for Real.pi_pos")
    
    # 1. Initialize Ingestor
    ingestor = GroundTruthIngestor(base_path=Path("research/case_studies"))

    # 2. Add the Verified Dependencies (The Edges)
    ingestor.add_dependency("Real.pi_pos", "lt_of_lt_of_le", implicit=False)
    ingestor.add_dependency("Real.pi_pos", "Real.two_le_pi", implicit=False)
    ingestor.add_dependency("Real.pi_pos", "zero_lt_two", implicit=True, tactic="simp")
    ingestor.add_dependency("Real.pi_pos", "Nat.zero_lt_succ", implicit=True, tactic="simp")

    logger.success(f"Verified Graph for Real.pi_pos built with {len(ingestor.dependencies)} edges.")
    
    targets = [d.target_name for d in ingestor.dependencies]
    
    print("\n--- COMPARISON REPORT ---")
    print("Heuristic Parser Found: ['Real.two_le_pi']")
    print(f"Ground Truth Found: {targets}")
    print("-------------------------\n")

if __name__ == "__main__":
    run_pi_pos_comparison()
