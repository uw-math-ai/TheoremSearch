"""Tests for TheoremSearchClient cache behaviour.

test_cache_hit: pure unit test, no network required (httpx mocked via respx).
test_live_search: integration test, requires network.  Skip with:
    pytest -m "not integration"
"""
from __future__ import annotations

import pytest
import httpx
import respx

from src.env.search_client import SearchResult, TheoremSearchClient

_MOCK_RESPONSE = {
    "theorems": [
        {
            "theorem_id": 42,
            "slogan_id": 7,
            "name": "First Isomorphism Theorem",
            "body": r"Let $f: G \to H$ be a group homomorphism. Then $G/\ker f \cong \mathrm{Im}\, f$.",
            "slogan": "Image quotient is isomorphic to quotient by kernel",
            "theorem_type": "Theorem",
            "link": "https://example.com/thm/42",
            "similarity": 0.871,
            "score": 0.871,
            "paper": {
                "source": "arxiv",
                "title": "Abstract Algebra",
                "primary_category": "math.GR",
                "year": 2020,
                "citations": 100,
                "journal_published": None,
            },
        }
    ]
}


@pytest.mark.asyncio
async def test_cache_hit(tmp_path):
    """Second identical search() call must hit the cache, not the network."""
    with respx.mock:
        route = respx.post("https://api.theoremsearch.com/search").mock(
            return_value=httpx.Response(200, json=_MOCK_RESPONSE)
        )

        client = TheoremSearchClient(cache_dir=str(tmp_path / "cache"))

        results1 = await client.search("group homomorphism", 5)
        results2 = await client.search("group homomorphism", 5)

        assert len(results1) == 1
        assert isinstance(results1[0], SearchResult)
        assert results1[0].theorem_id == 42
        assert results1[0].slogan == "Image quotient is isomorphic to quotient by kernel"
        assert results1[0].paper is not None

        assert len(results2) == 1
        assert results2[0].theorem_id == 42
        assert route.call_count == 1  # only one HTTP request despite two searches

        await client.close()


@pytest.mark.asyncio
async def test_different_keys_both_hit_network(tmp_path):
    """Different (query, k) pairs are cached independently."""
    with respx.mock:
        route = respx.post("https://api.theoremsearch.com/search").mock(
            return_value=httpx.Response(200, json=_MOCK_RESPONSE)
        )

        client = TheoremSearchClient(cache_dir=str(tmp_path / "cache"))

        await client.search("group homomorphism", 5)
        await client.search("group homomorphism", 10)  # different k
        await client.search("ring theory", 5)           # different query

        assert route.call_count == 3  # all three miss the cache

        await client.close()


@pytest.mark.asyncio
async def test_persistent_failure_returns_empty(tmp_path):
    """After 3 failed attempts the client returns [] and does not raise."""
    with respx.mock:
        respx.post("https://api.theoremsearch.com/search").mock(
            side_effect=httpx.ConnectError("network down")
        )

        client = TheoremSearchClient(cache_dir=str(tmp_path / "cache"))
        results = await client.search("some query", 5)

        assert results == []
        await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_live_search():
    """Integration: real TheoremSearch API, non-empty results expected."""
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmpdir:
        client = TheoremSearchClient(cache_dir=os.path.join(tmpdir, "cache"))
        results = await client.search("group homomorphism", 5)
        assert len(results) > 0, "Expected at least one result from live API"
        assert all(isinstance(r, SearchResult) for r in results)
        await client.close()
