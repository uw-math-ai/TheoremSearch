from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from src.data.id_mapping import IDMapper, MatchResult
from src.data.load_targets import Target
from src.env.search_client import SearchResult, TheoremSearchClient


@dataclass
class EnvState:
    target: Target
    retrieved_uuids: set[UUID]
    query_history: list[str]
    step_idx: int


class PremiseSelectionEnv:
    """Single-episode MDP for premise selection.

    reset() initialises state for a given target.
    step(query) issues one search, scores the reward, and returns
    (state, reward, done, info).  The info dict is the trajectory log entry
    for that step and is suitable for JSON serialisation.

    Reward:
      per-step:   |new ∩ true_deps| - alpha * |new \\ true_deps|
      terminal:   beta * (|retrieved ∩ true_deps| / |true_deps|)  (last step only)

    False-positive semantics: a result that fails to map to *any* UUID is NOT
    scored as an FP — we don't know what it is, so it's logged as
    dropped_no_match and excluded from reward.  A true FP is a confident match
    to a UUID that is NOT in the current target's true_deps.
    """

    def __init__(
        self,
        targets: dict[UUID, Target],
        search_client: TheoremSearchClient,
        id_mapper: IDMapper,
        config,
    ) -> None:
        self._targets = targets
        self._search = search_client
        self._mapper = id_mapper
        self._H = config.H
        self._k = config.k
        self._alpha = config.alpha
        self._beta = config.beta
        self._state: EnvState | None = None
        self._trajectory: list[dict] = []

    def reset(self, target_id: UUID) -> EnvState:
        target = self._targets[target_id]
        self._state = EnvState(
            target=target,
            retrieved_uuids=set(),
            query_history=[],
            step_idx=0,
        )
        self._trajectory = []
        return self._state

    async def step(self, query: str) -> tuple[EnvState, float, bool, dict]:
        assert self._state is not None, "call reset() before step()"
        state = self._state
        true_deps = state.target.true_dep_ids

        results: list[SearchResult] = await self._search.search(query, self._k)

        result_details: list[dict] = []
        candidate_uuids: set[UUID] = set()

        for r in results:
            match: MatchResult = self._mapper.map_int_to_uuid(r)
            if match.uuid is not None:
                candidate_uuids.add(match.uuid)
            result_details.append({
                "int_id": r.theorem_id,
                "mapped_uuid": str(match.uuid) if match.uuid else None,
                "match_score": match.score,
                "second_best_gap": match.second_best_gap,
                "low_confidence": match.low_confidence,
                "slogan": r.slogan,
                "name": r.name,
            })

        # Only score UUIDs we haven't credited before
        new_uuids = candidate_uuids - state.retrieved_uuids
        new_tps = len(new_uuids & true_deps)
        new_fps = len(new_uuids - true_deps)
        dropped_no_match = sum(1 for d in result_details if d["mapped_uuid"] is None)

        step_reward = new_tps - self._alpha * new_fps

        state.retrieved_uuids |= new_uuids
        state.query_history.append(query)
        state.step_idx += 1

        done = state.step_idx >= self._H
        terminal_reward = 0.0
        if done:
            recall = (
                len(state.retrieved_uuids & true_deps) / len(true_deps)
                if true_deps
                else 0.0
            )
            terminal_reward = self._beta * recall

        step_info = {
            "step": state.step_idx - 1,
            "query": query,
            "returned_results": result_details,
            "new_tps": new_tps,
            "new_fps": new_fps,
            "dropped_no_match": dropped_no_match,
            "step_reward": step_reward,
            "terminal_reward": terminal_reward,
        }
        self._trajectory.append(step_info)

        return state, step_reward + terminal_reward, done, step_info

    @property
    def trajectory(self) -> list[dict]:
        return list(self._trajectory)
