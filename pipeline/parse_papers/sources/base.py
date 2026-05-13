"""
Base class for a "Source" plugged into ``parse_papers``.

A Source is the upstream provider of a paper's LaTeX (e.g. arXiv, Lean
Community blueprints from GitHub, ...). Each Source knows how to:

  1. Materialize the LaTeX source for a paper into a local directory at parse
     time (called inside worker processes — must be self-contained).
  2. (Optional) Record a per-source parse attempt — e.g. arXiv writes to
     ``arxiv_parse_status``. Sources without such a table no-op.
  3. (Optional) Stage and flush preamble / bibliography rows into their own
     metadata table.

To add a new source, subclass ``Source`` and register an instance in
``pipeline/parse_papers/sources/__init__.py:SOURCES``.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from arXiTeX.types import ParsingMethod, StatementValidationLevel
from psycopg2.extensions import connection


@dataclass
class ParseAttempt:
    """One paper's parse attempt result, in source-agnostic form."""
    external_id: str
    when: datetime
    error: Optional[str]
    parsing_method: ParsingMethod
    validation_level: StatementValidationLevel
    preamble: Optional[str]
    bibliography: Optional[Dict[str, Any]]
    bibliography_bibtex: Optional[bool]


class Source(ABC):
    """An upstream paper source. ``name`` must equal ``paper.source``."""

    name: str

    # ------------------------------------------------------------------
    # Required: per-paper materialization (runs inside a worker process)
    # ------------------------------------------------------------------

    @abstractmethod
    def materialize(self, external_id: str, prefetched: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
        """
        Context manager (decorate the implementation with
        ``@contextlib.contextmanager``) yielding the kwargs to pass to
        ``arXiTeX.parse_paper`` for this paper.

        The source owns the lifetime of any temporary download — it must be
        cleaned up on context exit. Runs inside a worker process, so it
        must not need a DB connection.

        ``prefetched`` is whatever ``prefetch_metadata`` returned for this
        external_id (e.g. ``{"branch": "main", "src_path": "blueprint/src"}``
        for Lean Community). For sources that need no metadata it is an empty
        dict.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Optional: page-level prefetch (runs in the parent process)
    # ------------------------------------------------------------------

    def prefetch_metadata(self, conn: connection, external_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Return a mapping ``external_id -> kwargs`` for ``materialize``. Called
        once per page of papers, with a live DB connection. Default: empty
        dict for each id (sources that don't need any metadata).
        """
        return {eid: {} for eid in external_ids}

    # ------------------------------------------------------------------
    # SQL fragments used by the overwrite filter
    # ------------------------------------------------------------------

    def preamble_done_sql(self) -> Optional[str]:
        """
        SQL fragment that returns TRUE when ``paper`` already has a preamble
        recorded for this source. Used in the WHERE clause when --overwrite
        is off. ``paper`` is in scope.

        Return None if this source does not store preambles.
        """
        return None

    def bibliography_done_sql(self) -> Optional[str]:
        """Same shape as ``preamble_done_sql`` but for bibliography."""
        return None

    # ------------------------------------------------------------------
    # Optional: persist results
    # ------------------------------------------------------------------

    def record_attempt(self, attempt: ParseAttempt, batch: Dict[str, list]) -> None:
        """
        Stage rows from an attempt into ``batch`` (a dict whose keys this
        Source owns). Called once per paper in the parent process.

        Sources that don't need any per-attempt tracking can leave this alone.
        """
        pass

    def commit_batch(self, conn: connection, batch: Dict[str, list]) -> None:
        """
        Flush ``batch`` (which this Source populated via ``record_attempt``)
        to the DB. Called once per page after all attempts complete.
        """
        pass
