from __future__ import annotations

import json
import os
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from loguru import logger
from tqdm import tqdm

from .database import CorpusDatabase

LAKE_PATH = "/Users/simon/.elan/bin/lake"


def _extract_single_file(
    lean_file: Path, project_root: Path, extractor_path: Path
) -> str | None:
    """Helper for parallel execution of the Lean compiler."""
    try:
        cmd = [LAKE_PATH, "env", "lean", "--run", str(extractor_path), str(lean_file)]
        subprocess.run(
            cmd,
            cwd=project_root,
            capture_output=True,
            text=True,
            check=True,
            timeout=600,
        )
        # Search for the resulting JSON in build/ir
        return None  # Result is now found via filesystem scan
    except Exception:
        return None


class GroundTruthFactory:
    """
    High-performance engine for extracting and ingesting verified Lean data.
    """

    def __init__(self, db_path: Path = Path("formalized_graph/data/generated/global_corpus.db")):
        self.db = CorpusDatabase(db_path)
        self.extractor_lean = Path(__file__).parent.parent / "lean" / "ExtractData.lean"

    def process_project(
        self, project_path: Path, project_name: str, is_mathlib: bool = False
    ) -> None:
        logger.info(f"--- Starting Verified Extraction: {project_name} ---")
        project_id = self.db.add_project(project_name, is_mathlib=is_mathlib)

        lean_files = [
            f
            for f in project_path.rglob("*.lean")
            if f.name != "ExtractData.lean" and ".lake" not in str(f)
        ]
        logger.info(f"Found {len(lean_files)} Lean files to process.")

        temp_extractor = project_path / "ExtractData.lean"
        temp_extractor.write_text(self.extractor_lean.read_text())

        max_workers = os.cpu_count() or 4
        logger.info(f"Using {max_workers} parallel workers.")

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            future_to_file = {
                executor.submit(
                    _extract_single_file,
                    f.relative_to(project_path),
                    project_path,
                    Path("ExtractData.lean"),
                ): f
                for f in lean_files
            }
            for future in tqdm(
                as_completed(future_to_file),
                total=len(lean_files),
                desc="Extracting Ground Truth",
            ):
                future.result()

        # DISCOVERY: Find all JSONs generated in build/ir
        ast_files = list(project_path.rglob("*.ast.json"))
        self._ingest_ast_files(ast_files, project_id, project_path)

        if temp_extractor.exists():
            os.remove(temp_extractor)
        logger.success(f"--- {project_name} Ingested into Corpus ---")

    def _ingest_ast_files(
        self, ast_files: list[Path], project_id: int, project_root: Path
    ) -> None:
        logger.info(f"Ingesting {len(ast_files)} verified files into database...")
        all_nodes = []
        chunk_size = 5000

        for ast_path in tqdm(ast_files, desc="Processing JSONs"):
            if not ast_path.exists():
                continue
            try:
                # Universal path resolution logic
                path_str = str(ast_path)
                if "ir/" in path_str:
                    rel_lean_path = path_str.rsplit("ir/", maxsplit=1)[-1].replace(
                        ".ast.json", ".lean"
                    )
                else:
                    rel_lean_path = str(ast_path.relative_to(project_root)).replace(
                        ".ast.json", ".lean"
                    )

                with open(ast_path) as f:
                    data = json.load(f)
                    premises = data.get("premises", [])
                    for p in premises:
                        all_nodes.append(
                            (
                                project_id,
                                p["fullName"],
                                "unknown",
                                rel_lean_path,
                                "",  # docstring
                                "",  # statement
                            )
                        )

                if len(all_nodes) >= chunk_size:
                    self.db.bulk_insert_nodes(all_nodes)
                    all_nodes = []
            except Exception:
                continue

        if all_nodes:
            self.db.bulk_insert_nodes(all_nodes)
        logger.success("Database update complete.")
