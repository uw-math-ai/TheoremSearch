from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from uuid import UUID

from rapidfuzz import fuzz, process

from src.data.load_targets import DepStatement
from src.env.search_client import SearchResult

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    uuid: UUID | None
    score: float
    second_best_gap: float
    low_confidence: bool


def normalize(body: str) -> str:
    """Normalise a LaTeX body before ratio comparison.

    Strips \\label{...}, unescapes HTML entities, collapses whitespace, and
    removes trailing periods.  Lowercase is intentionally omitted — LaTeX is
    case-sensitive (\\Theta ≠ \\theta).
    """
    body = re.sub(r"\\label\{[^}]*\}", "", body)
    body = html.unescape(body)
    body = re.sub(r"\s+", " ", body)
    body = body.strip().rstrip(".")
    return body


class IDMapper:
    """Maps a TheoremSearch integer theorem_id to a Postgres statement UUID.

    Matching is done by rapidfuzz character-level ratio over the true-dep
    universe (union of dep bodies across all 100 targets).  Anything below
    match_threshold is returned as None.
    """

    def __init__(
        self,
        dep_stmts: list[DepStatement],
        match_threshold: float,
        low_confidence_gap: float = 5.0,
    ) -> None:
        self._threshold = match_threshold
        self._gap = low_confidence_gap
        self._norm_bodies: list[str] = [normalize(d.body) for d in dep_stmts]
        self._dep_uuids: list[UUID] = [d.statement_id for d in dep_stmts]

    def map_int_to_uuid(self, api_result: SearchResult) -> MatchResult:
        """Return the best-matching dep UUID, or None if below threshold.

        Logs the match score and the gap to second-best.  Low-confidence flag
        is set when best and second-best are within low_confidence_gap points.
        """
        if not self._norm_bodies:
            return MatchResult(uuid=None, score=0.0, second_best_gap=0.0, low_confidence=False)

        norm_api = normalize(api_result.body)
        # rapidfuzz.process.extract returns [(matched_str, score, index), ...]
        matches = process.extract(norm_api, self._norm_bodies, scorer=fuzz.ratio, limit=2)

        if not matches:
            return MatchResult(uuid=None, score=0.0, second_best_gap=0.0, low_confidence=False)

        _best_str, best_score, best_idx = matches[0]
        second_score = matches[1][1] if len(matches) > 1 else 0.0
        gap = best_score - second_score

        if best_score < self._threshold:
            logger.debug(
                "No match (score %.1f < threshold %.1f) for theorem_id=%s",
                best_score,
                self._threshold,
                api_result.theorem_id,
            )
            return MatchResult(uuid=None, score=best_score, second_best_gap=gap, low_confidence=False)

        low_confidence = gap < self._gap
        uuid = self._dep_uuids[best_idx]

        logger.debug(
            "Matched theorem_id=%s -> %s (score=%.1f, gap=%.1f, low_conf=%s)",
            api_result.theorem_id,
            uuid,
            best_score,
            gap,
            low_confidence,
        )
        return MatchResult(uuid=uuid, score=best_score, second_best_gap=gap, low_confidence=low_confidence)
