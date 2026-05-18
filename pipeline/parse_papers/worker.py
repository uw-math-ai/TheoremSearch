"""
Worker entry point for the ProcessPoolExecutor pool. Lives in its own module
(rather than ``__main__``) so ``pickle`` can resolve it from the worker
subprocesses, which never re-run the entrypoint script.
"""

from typing import Any, Dict

from arXiTeX import parse_paper
from .sources import SOURCES


def parse_in_worker(
    source_name: str,
    external_id: str,
    prefetched: Dict[str, Any],
    parse_kwargs: Dict[str, Any],
):
    src = SOURCES[source_name]
    with src.materialize(external_id, prefetched) as materialize_kwargs:
        return parse_paper(**materialize_kwargs, **parse_kwargs)
