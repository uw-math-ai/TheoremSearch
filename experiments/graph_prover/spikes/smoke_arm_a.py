"""Spike (c): ONE task end-to-end through arm A, K=1 — asserts a well-formed
provenance record and a parsed compile result land in the JSONL.

Needs: LPR cache artifacts, ANTHROPIC_API_KEY, built LPR_MATHLIB_DIR, and
cache/tasks_val.json (or pass --tid to build a throwaway task inline from the DB).

    python -m experiments.graph_prover.spikes.smoke_arm_a
"""
from __future__ import annotations

import json

from .. import config
from ..retrieval.arms import RetrievalContext
from ..scripts.run_experiment import run_static_arm


def main():
    tasks = json.loads((config.CACHE_DIR / "tasks_val.json").read_text())
    task = tasks[0]
    print(f"smoke task: {task['decl_name']} "
          f"({len(task['gold_proof_deps'])} gold deps, "
          f"{len(task['forbidden_ids'])} forbidden)")

    saved = config.BUDGET_K
    config.BUDGET_K = 1
    try:
        rec = run_static_arm(RetrievalContext(), task, "A")
    finally:
        config.BUDGET_K = saved

    line = rec.to_json()
    parsed = json.loads(line)
    assert parsed["attempts"], "no attempt recorded"
    a = parsed["attempts"][0]
    assert a["premises_offered"], "empty premise pool"
    assert all(c["provenance"].startswith("cosine#") for c in a["premises_offered"])
    assert a["compile"] is not None, "no compile result"
    assert a["cost_usd"] > 0, "cost not metered"
    assert parsed["steps"] and parsed["steps"][0]["query_kind"] == "slogan-vec"
    print(f"attempt: compiles={a['compile']['compiles']} "
          f"sorry_free={a['compile']['sorry_free']} "
          f"errors={len(a['compile']['errors'])} cost=${a['cost_usd']:.4f}")
    print("SMOKE PASS — record is well-formed")


if __name__ == "__main__":
    main()
