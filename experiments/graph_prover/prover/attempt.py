"""One plan-then-edit prover attempt: a SINGLE LLM call producing a complete proof.

No tool loop — compilation happens outside the call (compile/check_proof.py), which
keeps cost accounting exact and attempts comparable across arms. Client setup follows
experiments/lean_premise_retrieval/scripts/run_formalize_experiment.py; default model
claude-sonnet-4-6 (same as that experiment, for comparability), env GP_PROVER_MODEL.

Premature-convergence mitigation (compiler_loop_results.md finding #3) is baked into
the system prompt: premises are explicitly framed as fallible retrieval candidates.
"""
from __future__ import annotations

import os
import re

from .. import config
from ..provenance import Attempt, Candidate

SYS = (
    "You are proving a theorem in Lean 4 against Mathlib. The theorem statement is "
    "fixed — produce a complete, compiling, sorry-free proof.\n"
    "Rules:\n"
    "- Use FULLY-QUALIFIED names (no `open` is in scope).\n"
    "- Never use `sorry`, `admit`, `exact?`, `apply?`, `#check`, `#eval`, `import`, "
    "or new axioms.\n"
    "- The premises listed below are CANDIDATES from a retrieval system. Some are "
    "irrelevant or misleading. Use only what the proof actually needs; prefer your "
    "own knowledge of Mathlib naming when a premise looks wrong.\n"
    "- First write a short informal proof plan (3-6 lines), then the full Lean "
    "declaration `theorem cand ... := ...` in ONE fenced ```lean code block. The "
    "fenced block must contain the complete declaration, statement included, "
    "exactly as given (you may not alter the statement)."
)

FENCE_RE = re.compile(r"```(?:lean4?|)\s*\n(.*?)```", re.DOTALL)

_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic()
    return _client


def build_prompt(task: dict, pool: list[Candidate],
                 prev_attempt: Attempt | None) -> str:
    lines = ["## Theorem to prove\n```lean", task["statement_masked"].strip(), "```", ""]
    if pool:
        lines.append(f"## Candidate premises ({len(pool)}, best-first; "
                     "provenance in brackets)")
        for c in pool:
            sig = f" : {c.sig}" if c.sig else ""
            lines.append(f"- `{c.decl_name}`{sig}   [{c.provenance}]")
        lines.append("")
    if prev_attempt is not None and prev_attempt.compile is not None:
        lines.append("## Previous attempt (FAILED)\n```lean")
        lines.append(prev_attempt.proof_text.strip()[:4000])
        lines.append("```")
        lines.append("### Compiler errors")
        for e in prev_attempt.compile.errors[:10]:
            lines.append(f"- line {e['line']}: {e['message'][:400]}")
        if prev_attempt.compile.compiles and not prev_attempt.compile.sorry_free:
            lines.append("- proof compiles but still depends on sorryAx — "
                         "eliminate every sorry")
        lines.append("")
    lines.append("Write your plan, then the complete corrected declaration in one "
                  "```lean block.")
    return "\n".join(lines)


def parse_response(text: str, statement_masked: str) -> tuple[str, str]:
    """Returns (plan_text, declaration). Takes the LAST fenced lean block; if the model
    returned only a proof body, re-attach the fixed statement."""
    blocks = FENCE_RE.findall(text)
    decl = blocks[-1].strip() if blocks else ""
    plan = FENCE_RE.sub("", text).strip()[:2000]
    if decl and "theorem cand" not in decl and "lemma cand" not in decl:
        stmt = statement_masked.strip()
        stmt = re.sub(r":=\s*<MASK>\s*$", "", stmt).rstrip()
        stmt = re.sub(r":=\s*sorry\s*$", "", stmt).rstrip()
        if stmt.endswith(":="):
            decl = f"{stmt} {decl}"
        else:
            decl = f"{stmt} := {decl}"
    return plan, decl


def run_attempt(task: dict, pool: list[Candidate], idx: int, meter,
                prev_attempt: Attempt | None = None,
                temperature: float | None = 0.7) -> Attempt:
    prompt = build_prompt(task, pool, prev_attempt)
    client = _get_client()
    model = config.PROVER_MODEL
    kwargs = dict(model=model, max_tokens=4096, system=SYS,
                  messages=[{"role": "user", "content": prompt}])
    if temperature is not None:
        kwargs["temperature"] = temperature
    try:
        resp = client.messages.create(**kwargs)
    except Exception as e:  # temperature removed on newer models -> retry without
        if temperature is not None and "temperature" in str(e):
            kwargs.pop("temperature")
            resp = client.messages.create(**kwargs)
        else:
            raise
    text = "".join(b.text for b in resp.content if b.type == "text")
    cost = meter.record_anthropic(model, resp.usage.input_tokens,
                                  resp.usage.output_tokens)
    plan, decl = parse_response(text, task["statement_masked"])
    return Attempt(idx=idx, premises_offered=list(pool),
                   prompt_tokens=resp.usage.input_tokens,
                   completion_tokens=resp.usage.output_tokens,
                   cost_usd=cost, plan_text=plan, proof_text=decl)


def _selftest():
    """Pure-python: prompt assembly + response parsing (no API)."""
    task = {"statement_masked": "theorem cand (n : Nat) : n + 0 = n := <MASK>"}
    c = Candidate(statement_id="s1", decl_name="Nat.add_zero",
                  sig="∀ (n : ℕ), n + 0 = n", provenance="cosine#1")
    p = build_prompt(task, [c], None)
    ok1 = "Nat.add_zero" in p and "cosine#1" in p and "<MASK>" in p
    print(f"  [{'ok' if ok1 else 'MISMATCH'}] build_prompt carries premise + provenance")

    full = "Plan: apply add_zero.\n```lean\ntheorem cand (n : Nat) : n + 0 = n := Nat.add_zero n\n```"
    plan, decl = parse_response(full, task["statement_masked"])
    ok2 = decl.startswith("theorem cand") and "Nat.add_zero" in decl and "Plan" in plan
    print(f"  [{'ok' if ok2 else 'MISMATCH'}] parse_response full decl -> {decl!r}")

    body_only = "Use add_zero.\n```lean\nNat.add_zero n\n```"
    _, decl2 = parse_response(body_only, task["statement_masked"])
    ok3 = decl2 == "theorem cand (n : Nat) : n + 0 = n := Nat.add_zero n"
    print(f"  [{'ok' if ok3 else 'MISMATCH'}] parse_response body-only -> {decl2!r}")
    print("SELFTEST", "PASS" if ok1 and ok2 and ok3 else "FAIL")
    return ok1 and ok2 and ok3


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        sys.exit(0 if _selftest() else 1)
