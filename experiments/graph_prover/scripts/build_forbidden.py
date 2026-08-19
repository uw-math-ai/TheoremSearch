"""Forbidden sets: {target} ∪ transitive REVERSE dependencies, over ALL edge types.

A lemma whose *proof* uses the target leaks the answer just as much as one whose
signature does, so unlike lean_premise_retrieval's gold_edges.pkl (sig/extends/field
only) the reverse closure here streams every formal_dependency row (named cursor,
itersize 50k — the build_split.py pattern) and BFSes from each task target.

Reads  cache/tasks_<split>_pre.json  (from build_tasks.py)
Writes cache/forbidden_<split>.pkl   ({tid: [statement_id, ...]})
       cache/tasks_<split>.json      (tasks + forbidden_ids + forbidden_names)

    python -m experiments.graph_prover.scripts.build_forbidden --split val
"""
from __future__ import annotations

import argparse
import json
import pickle
from collections import defaultdict, deque

from .. import config

EDGES_SQL = "SELECT src_id::text, dep_id::text FROM formal_dependency"


def load_reverse_adjacency(conn) -> dict[str, list[str]]:
    """dep_id -> [src_id, ...]  ("who depends on X"), streamed."""
    rev = defaultdict(list)
    with conn.cursor(name="gp_edges") as cur:   # named cursor => server-side stream
        cur.itersize = 50_000
        cur.execute(EDGES_SQL)
        for i, (src, dep) in enumerate(cur):
            rev[dep].append(src)
            if i % 2_000_000 == 0 and i:
                print(f"  ... {i / 1e6:.0f}M edges")
    print(f"[edges] reverse adjacency over {len(rev)} nodes")
    return rev


def reverse_closure(rev: dict[str, list[str]], root: str) -> set[str]:
    seen = {root}
    q = deque([root])
    while q:
        for nxt in rev.get(q.popleft(), ()):
            if nxt not in seen:
                seen.add(nxt)
                q.append(nxt)
    return seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["val", "test"], default="val")
    args = ap.parse_args()

    pre = json.loads((config.CACHE_DIR / f"tasks_{args.split}_pre.json").read_text())
    print(f"[tasks] {len(pre)} pre-tasks")

    conn = config.get_rds_conn(statement_timeout_ms=0)  # streaming, no timeout
    rev = load_reverse_adjacency(conn)

    names = json.loads((config.LPR_CACHE / "decl_names.json").read_text())

    forbidden = {}
    for t in pre:
        closure = reverse_closure(rev, t["tid"])
        t["forbidden_ids"] = sorted(closure)
        t["forbidden_names"] = sorted({names[s] for s in closure if names.get(s)}
                                      | {t["decl_name"]})
        forbidden[t["tid"]] = t["forbidden_ids"]

    with open(config.CACHE_DIR / f"forbidden_{args.split}.pkl", "wb") as f:
        pickle.dump(forbidden, f)
    out = config.CACHE_DIR / f"tasks_{args.split}.json"
    out.write_text(json.dumps(pre, indent=1))
    sizes = sorted(len(v) for v in forbidden.values())
    print(f"[out] {out}; forbidden-set sizes min/median/max = "
          f"{sizes[0]}/{sizes[len(sizes) // 2]}/{sizes[-1]}")


if __name__ == "__main__":
    main()
