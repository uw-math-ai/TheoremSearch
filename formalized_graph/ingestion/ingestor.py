from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from .models import EntityKind, VerifiedDependency, VerifiedPremise


class GroundTruthIngestor:
    """
    Handles the structured ingestion of verified mathematical data.
    Decouples the extraction format (JSONL) from the internal storage.
    """

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.premises: dict[str, VerifiedPremise] = {}
        self.dependencies: list[VerifiedDependency] = []

    def ingest_premises(self, corpus_path: Path) -> None:
        """
        Parses a LeanDojo-style corpus file to identify all verified nodes.

        Args:
            corpus_path (Path): Path to the corpus.jsonl file.
        """
        logger.info(f"Ingesting premises from {corpus_path}...")
        count = 0

        if not corpus_path.exists():
            logger.error(f"Corpus file not found: {corpus_path}")
            return

        with corpus_path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    file_path = Path(data["path"])

                    for p in data.get("premises", []):
                        premise = VerifiedPremise(
                            full_name=p["fullName"],
                            kind=EntityKind.UNKNOWN,  # LeanDojo AST doesn't explicitly store kind
                            file_path=file_path,
                            module=data["module"],
                            docstring=p.get("doc", ""),
                        )
                        self.premises[premise.full_name] = premise
                        count += 1
                except Exception as e:
                    logger.warning(f"Failed to parse premise line: {e}")

        logger.success(f"Successfully ingested {count} verified premises.")

    def add_dependency(
        self,
        source: str,
        target: str,
        implicit: bool = False,
        tactic: str | None = None,
    ) -> None:
        """Programmatically adds a verified edge between two nodes."""
        dep = VerifiedDependency(
            source_name=source,
            target_name=target,
            is_implicit=implicit,
            tactic_context=tactic,
        )
        self.dependencies.append(dep)
        logger.debug(
            f"Added verified link: {source} -> {target} {'(implicit)' if implicit else ''}"
        )
