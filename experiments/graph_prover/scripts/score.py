"""Scoring: per-arm metrics + pairwise McNemar over a run directory.

Primary metric: sorry-free proof rate per dollar. Secondary: solve/compile rates,
attempts-to-solve, premise recall@POOL_K vs gold proof deps (attempt 1), fraction of
USED premises first surfaced via a graph/xform/mutation path (i.e. provenance tag not
cosine#...), token/cost totals, and the offline forbidden-leak audit.

McNemar is the exact binomial two-sided test on discordant (task solved by X not Y /
Y not X) pairs — no scipy dependency.

    python -m experiments.graph_prover.scripts.score --run-id val0
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict

from .. import config

GRAPH_PROVENANCE_PREFIXES = ("graph:", "xform:", "trigram:", "error-requery")


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact binomial p-value on discordant counts b, c."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def load_arm(run_dir, arm):
    p = run_dir / f"{arm}.jsonl"
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text().splitlines():
        r = json.loads(line)
        out[r["tid"]] = r
    return out


def arm_metrics(recs: dict, tasks_by_tid: dict) -> dict:
    n = len(recs)
    if n == 0:
        return {}
    solved = sum(r["solved"] for r in recs.values())
    compiled = sum(any(a.get("compile") and a["compile"]["compiles"]
                       for a in r["attempts"]) for r in recs.values())
    cost = sum(r["total_cost_usd"] for r in recs.values())
    att_to_solve = [len(r["attempts"]) for r in recs.values() if r["solved"]]
    errors = sum(1 for r in recs.values() if r.get("error"))

    recalls, graph_used, used_total, leaks = [], 0, 0, []
    for tid, r in recs.items():
        t = tasks_by_tid.get(tid)
        if t and r["attempts"]:
            gold = set(t["gold_proof_dep_names"]) or None
            first = r["attempts"][0]["premises_offered"]
            if gold:
                offered = {c["decl_name"] for c in first}
                recalls.append(len(gold & offered) / len(gold))
            forb = set(t["forbidden_names"])
            for a in r["attempts"]:
                for c in a["premises_offered"]:
                    if c["decl_name"] in forb:
                        leaks.append((tid, c["decl_name"]))
        prov = {}
        for a in r["attempts"]:
            for c in a["premises_offered"]:
                prov.setdefault(c["decl_name"], c["provenance"])
        final = r["attempts"][-1] if r["attempts"] else None
        if r["solved"] and final:
            for name in final.get("premises_used", []):
                used_total += 1
                if str(prov.get(name, "")).startswith(GRAPH_PROVENANCE_PREFIXES):
                    graph_used += 1

    return {
        "n": n, "solved": solved, "solve_rate": solved / n,
        "compile_rate": compiled / n, "cost_usd": round(cost, 3),
        "solved_per_dollar": round(solved / cost, 4) if cost else None,
        "mean_attempts_to_solve": round(sum(att_to_solve) / len(att_to_solve), 2)
                                  if att_to_solve else None,
        "premise_recall_at_pool": round(sum(recalls) / len(recalls), 4)
                                  if recalls else None,
        "used_premises_via_graph_path": f"{graph_used}/{used_total}",
        "orchestrator_errors": errors,
        "forbidden_leaks_offline_audit": len(leaks),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--split", default=None,
                    help="tasks file for gold labels (default: manifest's split)")
    args = ap.parse_args()
    run_dir = config.RESULTS_DIR / args.run_id
    manifest = json.loads((run_dir / "manifest.json").read_text())
    split = args.split or manifest["split"]
    tasks = json.loads((config.CACHE_DIR / f"tasks_{split}.json").read_text())
    tasks_by_tid = {t["tid"]: t for t in tasks}

    arms = {}
    for arm in manifest["arms"]:
        recs = load_arm(run_dir, arm)
        if recs:
            arms[arm] = recs

    print(f"run {args.run_id} (split {split}, model {manifest['prover_model']})\n")
    table = {arm: arm_metrics(recs, tasks_by_tid) for arm, recs in arms.items()}
    keys = ["n", "solved", "solve_rate", "compile_rate", "cost_usd",
            "solved_per_dollar", "mean_attempts_to_solve", "premise_recall_at_pool",
            "used_premises_via_graph_path", "orchestrator_errors",
            "forbidden_leaks_offline_audit"]
    w = max(len(k) for k in keys) + 2
    print(" " * w + "".join(f"{a:>16}" for a in table))
    for k in keys:
        print(f"{k:<{w}}" + "".join(f"{str(table[a].get(k)):>16}" for a in table))

    print("\nMcNemar (pairwise, exact two-sided on discordant solves):")
    pairs = [("A", "B"), ("B", "C"), ("C", "D"), ("D", "E"), ("A", "D"),
             ("A", "A-shuffled")]
    for x, y in pairs:
        if x not in arms or y not in arms:
            continue
        common = set(arms[x]) & set(arms[y])
        b = sum(1 for t in common if arms[x][t]["solved"] and not arms[y][t]["solved"])
        c = sum(1 for t in common if arms[y][t]["solved"] and not arms[x][t]["solved"])
        print(f"  {x} vs {y}: n={len(common)} {x}-only={b} {y}-only={c} "
              f"p={mcnemar_exact(b, c):.4f}")

    out = run_dir / "summary.json"
    out.write_text(json.dumps({"manifest": manifest, "metrics": table}, indent=1))
    print(f"\nsaved -> {out}")


if __name__ == "__main__":
    main()
