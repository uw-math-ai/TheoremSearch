"""Orchestrator: task x arm x attempt loop, K=6 compile attempts per task per arm.

Arms (approved plan §Step 2; budget = compile attempts, equal across arms):
  A          static semantic top-30, retries see errors but the same premises
  B          A + typed one-hop graph expansion (static pool)
  C          B + informal->formal graph_pack (static pool)
  D          C for attempt 1, then one retrieval mutation per retry
             (priority: trigram-repair -> error-requery -> forbid-tried -> seed-swap)
  E          C for attempt 1; on failure one 4-wide beam round (each mutation
             independently, one attempt per branch), then 1 final attempt on the
             best branch. 1 + 4 + 1 = 6.
  A-shuffled negative control: arm A premises taken from a DIFFERENT task
             (rotation by 1). If solve rate does not drop vs A, the prover ignores
             premises and the whole arm contrast is void.

One TaskRecord JSONL line per (task, arm) under results/<run_id>/<arm>.jsonl, plus
manifest.json recording models, prices, edge set, seed.

    python -m experiments.graph_prover.scripts.run_experiment \
        --split val --arms A,B,C,D,E --limit 20 --run-id val0
"""
from __future__ import annotations

import argparse
import json
import time

from .. import config
from ..costs import CostMeter, PRICES
from ..compile.check_proof import check_proof
from ..prover.attempt import run_attempt
from ..provenance import TaskRecord
from ..retrieval.arms import ARMS, RetrievalContext
from ..retrieval.mutations import MUTATION_OPS, mutate

STATIC_ARM_OF = {"A": "A", "B": "B", "C": "C", "A-shuffled": "A"}


def _compile_and_annotate(attempt, task):
    offered_names = {c.decl_name for c in attempt.premises_offered if c.decl_name}
    res = check_proof(attempt.proof_text,
                      forbidden_names=set(task["forbidden_names"]),
                      offered_names=offered_names)
    attempt.compile = res
    attempt.premises_used = sorted(offered_names & set(res.used_constants))
    return res.solved


def _attempt_score(a) -> tuple:
    """Lexicographic branch score: solved > compiles > fewer errors > cheaper."""
    c = a.compile
    return (int(c.solved), int(c.compiles), -len(c.errors), -a.cost_usd) \
        if c else (0, 0, -999, -a.cost_usd)


def run_static_arm(ctx, task, arm, pool_override=None) -> TaskRecord:
    rec = TaskRecord(tid=task["tid"], decl_name=task["decl_name"], arm=arm)
    meter = CostMeter()
    t0 = time.time()
    if pool_override is not None:
        pool, step = pool_override
    else:
        pool, step = ARMS[STATIC_ARM_OF[arm]](ctx, task, attempt_idx=0)
    rec.steps.append(step)
    prev = None
    for i in range(config.BUDGET_K):
        a = run_attempt(task, pool, i, meter, prev_attempt=prev)
        solved = _compile_and_annotate(a, task)
        rec.attempts.append(a)
        prev = a
        if solved:
            rec.solved = True
            break
    rec.total_cost_usd = meter.usd
    rec.wall_time_s = time.time() - t0
    return rec


def run_arm_d(ctx, task) -> TaskRecord:
    rec = TaskRecord(tid=task["tid"], decl_name=task["decl_name"], arm="D")
    meter = CostMeter()
    t0 = time.time()
    pool, step = ARMS["C"](ctx, task, attempt_idx=0)
    rec.steps.append(step)
    prev = None
    for i in range(config.BUDGET_K):
        if i > 0:
            op = MUTATION_OPS[(i - 1) % len(MUTATION_OPS)]
            pool, step = mutate(ctx, task, rec.attempts, op, attempt_idx=i)
            rec.steps.append(step)
        a = run_attempt(task, pool, i, meter, prev_attempt=prev)
        solved = _compile_and_annotate(a, task)
        rec.attempts.append(a)
        prev = a
        if solved:
            rec.solved = True
            break
    rec.total_cost_usd = meter.usd
    rec.wall_time_s = time.time() - t0
    return rec


def run_arm_e(ctx, task) -> TaskRecord:
    rec = TaskRecord(tid=task["tid"], decl_name=task["decl_name"], arm="E")
    meter = CostMeter()
    t0 = time.time()
    pool, step = ARMS["C"](ctx, task, attempt_idx=0)
    rec.steps.append(step)
    a0 = run_attempt(task, pool, 0, meter)
    a0.branch = "root"
    if _compile_and_annotate(a0, task):
        rec.attempts.append(a0)
        rec.solved = True
    else:
        rec.attempts.append(a0)
        branch_attempts = []
        for bi, op in enumerate(MUTATION_OPS[:config.BEAM_WIDTH], 1):
            bpool, bstep = mutate(ctx, task, [a0], op, attempt_idx=bi)
            rec.steps.append(bstep)
            ab = run_attempt(task, bpool, bi, meter, prev_attempt=a0)
            ab.branch = op
            solved = _compile_and_annotate(ab, task)
            rec.attempts.append(ab)
            branch_attempts.append((ab, bpool))
            if solved:
                rec.solved = True
                break
        if not rec.solved and branch_attempts:
            best, best_pool = max(branch_attempts, key=lambda t: _attempt_score(t[0]))
            af = run_attempt(task, best_pool, len(rec.attempts), meter,
                             prev_attempt=best)
            af.branch = f"final<-{best.branch}"
            if _compile_and_annotate(af, task):
                rec.solved = True
            rec.attempts.append(af)
    rec.total_cost_usd = meter.usd
    rec.wall_time_s = time.time() - t0
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["val", "test"], default="val")
    ap.add_argument("--arms", default="A,B,C,D,E",
                    help="comma list from A,B,C,D,E,A-shuffled")
    ap.add_argument("--limit", type=int, default=0, help="first N tasks only")
    ap.add_argument("--run-id", required=True)
    args = ap.parse_args()

    tasks = json.loads((config.CACHE_DIR / f"tasks_{args.split}.json").read_text())
    if args.limit:
        tasks = tasks[:args.limit]
    arms = [a.strip() for a in args.arms.split(",")]

    run_dir = config.RESULTS_DIR / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "manifest.json").write_text(json.dumps({
        "split": args.split, "arms": arms, "n_tasks": len(tasks),
        "budget_k": config.BUDGET_K, "pool_k": config.POOL_K,
        "prover_model": config.PROVER_MODEL, "prices": PRICES,
        "seed": config.SEED, "mathlib_dir": config.MATHLIB_DIR,
        "edge_types_env": __import__("os").environ.get("GP_EDGE_TYPES", "(default)"),
    }, indent=1))

    ctx = RetrievalContext()
    done: dict[str, set[str]] = {}
    for arm in arms:              # resumability: skip (task, arm) already recorded
        p = run_dir / f"{arm}.jsonl"
        done[arm] = set()
        if p.exists():
            for line in p.read_text().splitlines():
                done[arm].add(json.loads(line)["tid"])

    for ti, task in enumerate(tasks):
        # rotated premises for the shuffled control: task i gets task i+1's retrieval
        shuffled_src = tasks[(ti + 1) % len(tasks)]
        for arm in arms:
            if task["tid"] in done[arm]:
                continue
            try:
                if arm == "D":
                    rec = run_arm_d(ctx, task)
                elif arm == "E":
                    rec = run_arm_e(ctx, task)
                elif arm == "A-shuffled":
                    pool, step = ARMS["A"](ctx, shuffled_src, attempt_idx=0)
                    # re-mask against THIS task's forbidden set (leak gate still holds)
                    pool = [c for c in pool
                            if c.statement_id not in set(task["forbidden_ids"])
                            and c.decl_name not in set(task["forbidden_names"])]
                    rec = run_static_arm(ctx, task, arm, pool_override=(pool, step))
                else:
                    rec = run_static_arm(ctx, task, arm)
            except Exception as e:  # record the failure, keep the run going
                rec = TaskRecord(tid=task["tid"], decl_name=task["decl_name"],
                                 arm=arm, error=f"{type(e).__name__}: {e}")
            with open(run_dir / f"{arm}.jsonl", "a") as f:
                f.write(rec.to_json() + "\n")
            print(f"[{ti + 1}/{len(tasks)}] {arm} {task['decl_name']}: "
                  f"solved={rec.solved} attempts={len(rec.attempts)} "
                  f"${rec.total_cost_usd:.3f}"
                  + (f" ERROR={rec.error}" if rec.error else ""))

    print(f"\ndone -> {run_dir}\nscore: python -m experiments.graph_prover.scripts.score "
          f"--run-id {args.run_id}")


if __name__ == "__main__":
    main()
