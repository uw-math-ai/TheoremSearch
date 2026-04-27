from __future__ import annotations

from src.env.environment import EnvState


def format_state(state: EnvState, H: int) -> str:
    """Format the current MDP state as the initial user message for the LLM.

    Shows target identity (slogan / label / ref), the full body, optional
    surrounding context, and the query history so far.
    """
    t = state.target
    lines: list[str] = []

    header_parts: list[str] = []
    if t.label:
        header_parts.append(f"Label: {t.label}")
    if t.ref:
        header_parts.append(f"Ref: {t.ref}")
    if header_parts:
        lines.append("  ".join(header_parts))

    lines.append(f"\nBody:\n{t.body}")

    if t.pre_context:
        lines.append(f"\nContext (before):\n{t.pre_context}")
    if t.post_context:
        lines.append(f"\nContext (after):\n{t.post_context}")

    lines.append(f"\nYou may issue up to {H} search queries.")

    if state.query_history:
        qs = "\n".join(f"  {i+1}. {q}" for i, q in enumerate(state.query_history))
        lines.append(f"\nQueries issued so far ({state.step_idx}/{H}):\n{qs}")
    else:
        lines.append("\nNo queries issued yet.")

    return "\n".join(lines)


def format_search_results(step_info: dict) -> str:
    """Format a step's returned results as the tool-result message for the LLM.

    Shows slogans and names — full bodies are omitted to stay within context.
    """
    results = step_info.get("returned_results", [])
    query = step_info.get("query", "")
    step = step_info.get("step", "?")

    lines = [f'Search results for "{query}" (step {step}):']
    for i, r in enumerate(results, 1):
        slogan = r.get("slogan") or r.get("name") or "(no slogan)"
        lines.append(f"  [{i}] {slogan}")

    if not results:
        lines.append("  (no results)")

    return "\n".join(lines)
