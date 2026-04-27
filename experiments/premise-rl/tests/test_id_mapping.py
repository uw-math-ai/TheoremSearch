"""Tests for IDMapper and the normalize() function.

Unit tests (no external services):
    test_normalizer_idempotence
    test_no_match_below_threshold
    test_low_confidence_flagging

Integration tests (require DB + TheoremSearch API):
    test_round_trip_uuid_recovery   — marked @pytest.mark.integration
"""
from __future__ import annotations

import pytest
from uuid import UUID

from src.data.id_mapping import IDMapper, MatchResult, normalize
from src.data.load_targets import DepStatement
from src.env.search_client import SearchResult


# ── Normalizer tests ────────────────────────────────────────────────────────────

NORMALIZER_CASES = [
    r"Let $G$ be a \label{thm:main} group.",
    r"If $f: A \to B$ &amp; $g: B \to C$,   then    $g \circ f$ is continuous.",
    r"   \label{eq:1}  $\Theta \neq \theta$.   ",
    r"$x + y = 0$.",  # trailing period
    "already normalised",
    "",  # empty string
]


@pytest.mark.parametrize("body", NORMALIZER_CASES)
def test_normalizer_idempotence(body: str):
    once = normalize(body)
    twice = normalize(once)
    assert once == twice, f"normalize not idempotent for: {body!r}"


def test_normalize_strips_label():
    result = normalize(r"Some \label{thm:foo} body.")
    assert r"\label" not in result


def test_normalize_unescapes_html():
    result = normalize(r"$a &amp; b$")
    assert "&amp;" not in result
    assert "&" in result


def test_normalize_collapses_whitespace():
    result = normalize("a   b\t\nc")
    assert "  " not in result
    assert result == "a b c"


def test_normalize_strips_trailing_period():
    assert normalize("A theorem.") == "A theorem"


def test_normalize_preserves_case():
    # LaTeX is case-sensitive: \\Theta must NOT become \\theta
    body = r"$\Theta$ and $\theta$ are different"
    assert normalize(body) == body


# ── IDMapper unit tests ─────────────────────────────────────────────────────────

UUID_A = UUID("00000000-0000-0000-0000-000000000001")
UUID_B = UUID("00000000-0000-0000-0000-000000000002")


def _make_dep(uuid: UUID, body: str) -> DepStatement:
    return DepStatement(
        statement_id=uuid,
        body=body,
        kind="Theorem",
        paper_id=UUID("99999999-0000-0000-0000-000000000000"),
    )


def _make_sr(theorem_id: int, body: str) -> SearchResult:
    return SearchResult(
        theorem_id=theorem_id, slogan_id=theorem_id * 10,
        name="test", body=body, slogan="test slogan",
        theorem_type="Theorem", link=None,
        similarity=0.9, score=0.9, paper=None,
    )


def test_exact_body_match():
    body = r"Let $G$ be a finite group of order $p^2$. Then $G$ is abelian."
    dep = _make_dep(UUID_A, body)
    mapper = IDMapper([dep], match_threshold=85.0)

    sr = _make_sr(1, body)
    result = mapper.map_int_to_uuid(sr)

    assert result.uuid == UUID_A
    assert result.score == pytest.approx(100.0)
    assert not result.low_confidence


def test_no_match_below_threshold():
    """Unrelated body must return None regardless of threshold."""
    dep = _make_dep(UUID_A, r"Let $G$ be a finite group of order $p^2$.")
    mapper = IDMapper([dep], match_threshold=85.0)

    sr = _make_sr(99, "this is not a real theorem and has nothing in common")
    result = mapper.map_int_to_uuid(sr)

    assert result.uuid is None


def test_empty_dep_universe_returns_none():
    mapper = IDMapper([], match_threshold=85.0)
    sr = _make_sr(1, "some body")
    result = mapper.map_int_to_uuid(sr)
    assert result.uuid is None
    assert result.score == 0.0


def test_low_confidence_flagged_when_gap_small():
    """When best and second-best are within low_confidence_gap, flag is set."""
    # Two very similar bodies so the gap between first and second match is small
    body1 = r"Let $G$ be a finite abelian group."
    body2 = r"Let $G$ be a finite abelian group of prime order."
    dep_a = _make_dep(UUID_A, body1)
    dep_b = _make_dep(UUID_B, body2)
    mapper = IDMapper([dep_a, dep_b], match_threshold=50.0, low_confidence_gap=20.0)

    # Query with body1 — should match dep_a best but gap to dep_b may be small
    sr = _make_sr(1, body1)
    result = mapper.map_int_to_uuid(sr)

    # Only check the flag when there actually IS a small gap
    if result.uuid is not None:
        if result.second_best_gap < 20.0:
            assert result.low_confidence
        else:
            assert not result.low_confidence


def test_correct_uuid_returned_among_multiple_deps():
    dep_a = _make_dep(UUID_A, r"Let $R$ be a commutative ring with unit.")
    dep_b = _make_dep(UUID_B, r"Let $G$ be a finite group of order $p^2$.")
    mapper = IDMapper([dep_a, dep_b], match_threshold=85.0)

    sr = _make_sr(1, r"Let $G$ be a finite group of order $p^2$.")
    result = mapper.map_int_to_uuid(sr)

    assert result.uuid == UUID_B


# ── Integration test (requires DB + TheoremSearch API) ─────────────────────────

@pytest.mark.asyncio
@pytest.mark.integration
async def test_round_trip_uuid_recovery():
    """For 5 sampled dep statements, query TheoremSearch and verify UUID recovery."""
    import os
    import random
    import tempfile
    from dotenv import load_dotenv

    load_dotenv()

    from src.data.load_targets import load_all_data
    from src.env.search_client import TheoremSearchClient

    _targets, dep_stmts = load_all_data()
    assert len(dep_stmts) > 0, "No dep statements loaded — check DB connection"

    sample = random.sample(dep_stmts, min(5, len(dep_stmts)))
    mapper = IDMapper(dep_stmts, match_threshold=85.0)

    with tempfile.TemporaryDirectory() as tmpdir:
        client = TheoremSearchClient(cache_dir=os.path.join(tmpdir, "cache"))

        recovered = 0
        for dep in sample:
            query = dep.body[:100]
            results = await client.search(query, k=10)
            if not results:
                continue
            for r in results:
                match = mapper.map_int_to_uuid(r)
                if match.uuid == dep.statement_id:
                    recovered += 1
                    break

        await client.close()

    # At least 3 of 5 should round-trip successfully
    assert recovered >= 3, (
        f"Only {recovered}/5 dep statements recovered via round-trip. "
        "Check calibration threshold and corpus alignment."
    )
