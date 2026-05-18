"""arXiv source. arXiTeX's ``parse_paper`` handles the download itself."""

from contextlib import contextmanager
from typing import Any, Dict, Iterator

from psycopg2.extras import Json

from rds.utils.upsert import upsert_rows, update_rows
from .base import ParseAttempt, Source


class ArxivSource(Source):
    name = "arXiv"

    @contextmanager
    def materialize(self, external_id: str, prefetched: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
        # arXiTeX downloads to its own tempdir when given arxiv_id.
        yield {"arxiv_id": external_id}

    def preamble_done_sql(self) -> str:
        return """
            paper.source = 'arXiv' AND EXISTS (
                SELECT 1 FROM arxiv_paper_metadata
                WHERE arxiv_id = paper.external_id AND preamble IS NOT NULL
            )
        """

    def bibliography_done_sql(self) -> str:
        return """
            paper.source = 'arXiv' AND EXISTS (
                SELECT 1 FROM arxiv_paper_metadata
                WHERE arxiv_id = paper.external_id AND bibliography IS NOT NULL
            )
        """

    def record_attempt(self, attempt: ParseAttempt, batch: Dict[str, list]) -> None:
        # Every attempt (success or failure) gets a parse_status row.
        batch.setdefault("parse_status", []).append({
            "arxiv_id": attempt.external_id,
            "last_parse_attempt_at": attempt.when,
            "error": attempt.error,
            "parsing_method": attempt.parsing_method.value,
            "validation_level": attempt.validation_level.value,
        })
        if attempt.preamble is not None:
            batch.setdefault("preamble", []).append({
                "arxiv_id": attempt.external_id,
                "preamble": attempt.preamble,
            })
        if attempt.bibliography:
            batch.setdefault("bibliography", []).append({
                "arxiv_id": attempt.external_id,
                "bibliography": Json(attempt.bibliography),
                "bibtex": attempt.bibliography_bibtex,
            })

    def commit_batch(self, conn, batch: Dict[str, list]) -> None:
        if batch.get("parse_status"):
            upsert_rows(
                conn,
                table="arxiv_parse_status",
                rows=batch["parse_status"],
                on_conflict={
                    "with": ["arxiv_id"],
                    "replace": ["last_parse_attempt_at", "error", "parsing_method", "validation_level"],
                },
            )
        if batch.get("preamble"):
            update_rows(
                conn,
                table="arxiv_paper_metadata",
                rows=batch["preamble"],
                where=["arxiv_id"],
            )
        if batch.get("bibliography"):
            update_rows(
                conn,
                table="arxiv_paper_metadata",
                rows=batch["bibliography"],
                where=["arxiv_id"],
                casts={"bibliography": "jsonb"},
            )
