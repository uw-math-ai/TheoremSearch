"""GPT policy using OpenAI Chat Completions with native function/tool use.

Uses the Responses API-style multi-turn pattern (full conversation history in
each call) rather than the stateful /v1/responses endpoint, which keeps the
implementation independent of server-side conversation state and makes the
diskcache on the search client the only shared state across runs.

Pin the exact dated snapshot in configs/smoke_test.yaml.  Never use the
floating alias (gpt-5.4) — it will drift mid-experiment.
"""
from __future__ import annotations

import json
import logging
from uuid import UUID

from openai import AsyncOpenAI

from src._config import Config
from src.env.environment import PremiseSelectionEnv
from src.env.prompts import format_search_results, format_state

logger = logging.getLogger(__name__)

_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_theorems",
        "description": (
            "Search the theorem corpus for mathematical statements by natural-language query. "
            "Returns the top-k results, ranked by embedding similarity over slogan text. "
            "Use this to find logical predecessors (lemmas, propositions) cited by the target's proof."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language description of the mathematical result to find.",
                },
                "k": {
                    "type": "integer",
                    "description": "Number of results to return (default: 10, max: 20).",
                },
            },
            "required": ["query"],
        },
    },
}


def _assistant_msg_to_dict(msg) -> dict:
    """Convert an OpenAI ChatCompletionMessage to a plain dict for the history list."""
    d: dict = {"role": "assistant"}
    if msg.content is not None:
        d["content"] = msg.content
    if msg.tool_calls:
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": tc.type,
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in msg.tool_calls
        ]
    return d


async def run_episode(
    env: PremiseSelectionEnv,
    target_id: UUID,
    client: AsyncOpenAI,
    config: Config,
    system_prompt: str,
) -> dict:
    """Run one full episode for target_id and return a trajectory dict.

    Terminates when:
    - The model declines to call search_theorems (finish_reason != "tool_calls")
    - env returns done=True (H queries issued)
    - Safety cap of H tool calls reached

    Temperature = 0 for reproducibility.
    """
    state = env.reset(target_id)

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": format_state(state, config.H)},
    ]

    trajectory: list[dict] = []
    done = False

    while not done and state.step_idx < config.H:
        try:
            response = await client.chat.completions.create(
                model=config.model,
                messages=messages,
                tools=[_SEARCH_TOOL],
                tool_choice="auto",
                temperature=0,
            )
        except Exception as exc:
            logger.error("OpenAI call failed for target %s: %s", target_id, exc)
            break

        choice = response.choices[0]
        messages.append(_assistant_msg_to_dict(choice.message))

        if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
            # Model declined to call the tool — episode ends early
            logger.debug("Model stopped calling tool at step %d", state.step_idx)
            break

        # Process every tool call in this turn.
        # OpenAI requires one "tool" reply per tool_call_id in the assistant
        # message, so we must respond to all of them even if the budget runs
        # out mid-turn or a call is malformed.
        for tool_call in choice.message.tool_calls:
            if done or state.step_idx >= config.H:
                # Budget exhausted: send a placeholder so the history stays valid.
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": "(search budget exhausted)",
                })
                continue

            if tool_call.function.name != "search_theorems":
                logger.warning("Unexpected tool call: %s", tool_call.function.name)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": "Unknown tool.",
                })
                continue

            try:
                args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError as exc:
                logger.error("Malformed tool arguments: %s", exc)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": "Error: malformed arguments.",
                })
                continue

            query: str = args["query"]
            k: int = int(args.get("k", config.k))

            state, _reward, done, step_info = await env.step(query)
            trajectory.append(step_info)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": format_search_results(step_info),
            })

    true_deps = env._state.target.true_dep_ids
    retrieved = env._state.retrieved_uuids
    recall = len(retrieved & true_deps) / len(true_deps) if true_deps else 0.0

    all_queries = [s["query"] for s in trajectory]
    unique_queries = len(set(all_queries))
    total_fps = sum(s["new_fps"] for s in trajectory)
    terminal_reward = trajectory[-1]["terminal_reward"] if trajectory else 0.0

    # Count low-confidence and total accepted matches across the episode
    n_low_conf = sum(
        1
        for step in trajectory
        for r in step["returned_results"]
        if r.get("low_confidence") and r.get("mapped_uuid") is not None
    )
    n_total_matches = sum(
        1
        for step in trajectory
        for r in step["returned_results"]
        if r.get("mapped_uuid") is not None
    )
    total_dropped = sum(s["dropped_no_match"] for s in trajectory)

    return {
        "target_id": str(target_id),
        "n_true_deps": len(true_deps),
        "trajectory": trajectory,
        "retrieved_uuids": [str(u) for u in retrieved],
        "recall": recall,
        "total_queries": len(all_queries),
        "unique_queries": unique_queries,
        "total_fps": total_fps,
        "terminal_reward": terminal_reward,
        "total_dropped_no_match": total_dropped,
        "n_low_confidence_matches": n_low_conf,
        "n_total_matches": n_total_matches,
    }
