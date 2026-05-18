"""Unit tests for environment reward math.

No external services required — uses fake search client and fake ID mapper.
"""
from __future__ import annotations

import pytest
from uuid import UUID

from src.data.id_mapping import MatchResult
from src.data.load_targets import Target
from src.env.environment import PremiseSelectionEnv
from src.env.search_client import SearchResult

# ── UUID fixtures ──────────────────────────────────────────────────────────────
A = UUID("00000000-0000-0000-0000-000000000001")   # TP deps of the test target
B = UUID("00000000-0000-0000-0000-000000000002")
C = UUID("00000000-0000-0000-0000-000000000003")
X = UUID("00000000-0000-0000-0000-000000000004")   # FP: in universe, not in target
Y = UUID("00000000-0000-0000-0000-000000000005")   # FP: in universe, not in target
TARGET_ID = UUID("10000000-0000-0000-0000-000000000000")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _sr(theorem_id: int) -> SearchResult:
    return SearchResult(
        theorem_id=theorem_id, slogan_id=theorem_id * 10,
        name=f"thm-{theorem_id}", body=f"body of theorem {theorem_id}",
        slogan=f"slogan of theorem {theorem_id}", theorem_type="Theorem",
        link=None, similarity=0.9, score=0.9, paper=None,
    )


def _match(uuid: UUID | None, score: float = 95.0) -> MatchResult:
    return MatchResult(uuid=uuid, score=score, second_best_gap=20.0, low_confidence=False)


def _target(true_dep_ids: set[UUID]) -> Target:
    return Target(
        statement_id=TARGET_ID,
        body="Let G be a group.",
        proof="Follows from definitions.",
        kind="Theorem",
        paper_id=UUID("20000000-0000-0000-0000-000000000000"),
        label=None, ref=None, pre_context=None, post_context=None,
        true_dep_ids=true_dep_ids,
    )


class _FakeSearchClient:
    def __init__(self, results_by_query: dict[str, list[SearchResult]]) -> None:
        self._results = results_by_query

    async def search(self, query: str, k: int) -> list[SearchResult]:
        return self._results.get(query, [])[:k]


class _FakeIDMapper:
    def __init__(self, mapping: dict[int, MatchResult]) -> None:
        self._mapping = mapping

    def map_int_to_uuid(self, api_result: SearchResult) -> MatchResult:
        return self._mapping.get(api_result.theorem_id,
                                 MatchResult(uuid=None, score=0.0, second_best_gap=0.0, low_confidence=False))


class _FakeConfig:
    H = 3
    k = 5
    alpha = 0.1
    beta = 10.0
    match_threshold = 85.0
    low_confidence_gap = 5.0


# sr objects for theorem_ids 1-5
sr = {i: _sr(i) for i in range(1, 6)}

# UUID mapping: int id -> matched UUID
_MAPPER = _FakeIDMapper({
    1: _match(A),          # TP for target
    2: _match(B),          # TP for target
    3: _match(C),          # TP for target
    4: _match(X),          # FP for target (dep of another)
    5: _match(Y),          # FP for target (dep of another)
    # theorem_id=99 is absent -> maps to None
})

_SEARCH = _FakeSearchClient({
    "q1": [sr[1], sr[4]],          # A (TP), X (FP)
    "q2": [sr[2], sr[5]],          # B (TP), Y (FP)
    "q3": [sr[3]],                  # C (TP)
    "q_dup": [sr[1], sr[4]],       # same result as q1 (duplicate scenario)
    "q_drop": [SearchResult(
        theorem_id=99, slogan_id=990,
        name="unknown", body="completely unrelated",
        slogan="unknown", theorem_type="Lemma",
        link=None, similarity=0.1, score=0.1, paper=None,
    )],
})


def _env() -> PremiseSelectionEnv:
    target = _target({A, B, C})
    return PremiseSelectionEnv(
        targets={TARGET_ID: target},
        search_client=_SEARCH,
        id_mapper=_MAPPER,
        config=_FakeConfig(),
    )


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_three_step_mixed_tps_fps():
    """3 steps with TPs and FPs; hand-computed cumulative reward."""
    env = _env()
    env.reset(TARGET_ID)

    # Step 1: A (TP), X (FP) -> step_reward = 1 - 0.1 = 0.9, terminal = 0
    _, r1, done1, info1 = await env.step("q1")
    assert not done1
    assert info1["new_tps"] == 1
    assert info1["new_fps"] == 1
    assert abs(info1["step_reward"] - 0.9) < 1e-9
    assert info1["terminal_reward"] == 0.0
    assert abs(r1 - 0.9) < 1e-9

    # Step 2: B (TP), Y (FP) -> step_reward = 0.9, terminal = 0
    _, r2, done2, info2 = await env.step("q2")
    assert not done2
    assert info2["new_tps"] == 1
    assert info2["new_fps"] == 1
    assert abs(info2["step_reward"] - 0.9) < 1e-9
    assert info2["terminal_reward"] == 0.0

    # Step 3 (last): C (TP) -> step_reward = 1.0, terminal = 10.0 * (3/3) = 10.0
    _, r3, done3, info3 = await env.step("q3")
    assert done3
    assert info3["new_tps"] == 1
    assert info3["new_fps"] == 0
    assert abs(info3["step_reward"] - 1.0) < 1e-9
    assert abs(info3["terminal_reward"] - 10.0) < 1e-9
    assert abs(r3 - 11.0) < 1e-9  # step + terminal

    # Cumulative: 0.9 + 0.9 + 11.0 = 12.8
    assert abs(r1 + r2 + r3 - 12.8) < 1e-9


@pytest.mark.asyncio
async def test_duplicate_query_zero_reward():
    """Issuing the same query twice must yield zero new TPs and zero new FPs on repeat."""
    env = _env()
    env.reset(TARGET_ID)

    _, r1, _, info1 = await env.step("q_dup")
    assert r1 > 0  # first time: A (TP), X (FP) -> 0.9

    _, r2, _, info2 = await env.step("q_dup")  # identical query
    assert info2["new_tps"] == 0
    assert info2["new_fps"] == 0
    assert info2["step_reward"] == 0.0


@pytest.mark.asyncio
async def test_terminal_bonus_fires_only_on_last_step():
    """terminal_reward must be 0 on all non-final steps."""
    env = _env()
    env.reset(TARGET_ID)

    _, _, _, info1 = await env.step("q1")
    assert info1["terminal_reward"] == 0.0

    _, _, _, info2 = await env.step("q2")
    assert info2["terminal_reward"] == 0.0

    _, _, done3, info3 = await env.step("q3")
    assert done3
    assert info3["terminal_reward"] > 0.0


@pytest.mark.asyncio
async def test_dropped_no_match_zero_reward_zero_penalty():
    """API result with no UUID match is logged as dropped_no_match; no reward or penalty."""
    env = _env()
    env.reset(TARGET_ID)

    _, r, _, info = await env.step("q_drop")
    assert info["dropped_no_match"] == 1
    assert info["new_tps"] == 0
    assert info["new_fps"] == 0
    assert info["step_reward"] == 0.0
    assert r == 0.0  # (terminal_reward is 0 because not last step here either)
