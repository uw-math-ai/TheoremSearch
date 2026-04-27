from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import diskcache
import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.theoremsearch.com"


@dataclass
class SearchResult:
    theorem_id: int
    slogan_id: int
    name: str | None
    body: str
    slogan: str | None
    theorem_type: str | None
    link: str | None
    similarity: float
    score: float
    paper: dict[str, Any] | None


class TheoremSearchClient:
    """Async wrapper around POST /search with diskcache and exponential-backoff retry.

    Never raises into a rollout — persistent failures return an empty list with a warning.
    """

    def __init__(self, cache_dir: str) -> None:
        self._cache = diskcache.Cache(cache_dir)
        self._http = httpx.AsyncClient(timeout=30.0)

    async def search(self, query: str, k: int) -> list[SearchResult]:
        cache_key = (query, k)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        results = await self._fetch(query, k)
        self._cache.set(cache_key, results)
        return results

    async def _fetch(self, query: str, k: int) -> list[SearchResult]:
        payload = {"query": query, "n_results": k}
        for attempt in range(3):
            try:
                resp = await self._http.post(f"{_BASE_URL}/search", json=payload)
                resp.raise_for_status()
                return [_parse_result(r) for r in resp.json().get("theorems", [])]
            except Exception as exc:
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                else:
                    logger.warning("TheoremSearch failed after 3 attempts: %s", exc)
                    return []
        return []

    async def close(self) -> None:
        await self._http.aclose()
        self._cache.close()


def _parse_result(raw: dict[str, Any]) -> SearchResult:
    return SearchResult(
        theorem_id=raw["theorem_id"],
        slogan_id=raw["slogan_id"],
        name=raw.get("name"),
        body=raw.get("body", ""),
        slogan=raw.get("slogan"),
        theorem_type=raw.get("theorem_type"),
        link=raw.get("link"),
        similarity=raw.get("similarity", 0.0),
        score=raw.get("score", 0.0),
        paper=raw.get("paper"),
    )
