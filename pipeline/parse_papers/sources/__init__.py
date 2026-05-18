"""
Source registry for ``parse_papers``. Importing this module is the canonical
way to discover supported sources — adding a new entry here is all it takes to
plug a new ``Source`` into the parsing pipeline.
"""

from .arxiv import ArxivSource
from .base import ParseAttempt, Source
from .lean_community import LeanCommunitySource


SOURCES: dict[str, Source] = {
    src.name: src
    for src in (ArxivSource(), LeanCommunitySource())
}


__all__ = ["SOURCES", "Source", "ParseAttempt"]
