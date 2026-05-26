"""P5: score formalization completions, no-RAG vs RAG.

Given a completions json ({tid: {no_rag, rag}}) and the eval set, computes for
each condition:
  - typecheck rate : fraction whose statement elaborates in Lean+Mathlib
  - premise recall : fraction of a target's gold premise names that appear
                     (as whole identifiers) in the produced statement
Both stratified by needs_rare, and reported as the RAG - no-RAG delta. The delta
is robust to slogan provenance (slogan identical in both conditions).

    python scripts/score_formalization.py \
        --completions cache/out_Qwen_Qwen3-8B.json --eval cache/formalization_eval_rag.pkl
"""
import argparse
import json
import pickle
import re
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.run_typecheck import typecheck


def prem_recall(stmt, premise_names):
    got = 0
    for n in premise_names:
        if not n:
            continue
        # whole-identifier match (Lean identifiers incl. dots)
        if re.search(rf"(?<![\w.]){re.escape(n)}(?![\w])", stmt):
            got += 1
    return got / max(len(premise_names), 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--completions", required=True)
    ap.add_argument("--eval", required=True)
    args = ap.parse_args()

    comp = json.load(open(args.completions))
    ev = pickle.load(open(args.eval, "rb"))
    tids = [t for t in ev if t in comp]
    print(f"scoring {len(tids)} targets from {Path(args.completions).name}")

    # batched typecheck per condition
    tc = {}
    for cond in ("no_rag", "rag"):
        types = [comp[t][cond] for t in tids]
        print(f"  typechecking {cond} ({len(types)})...", flush=True)
        tc[cond] = dict(zip(tids, typecheck(types)))

    def agg(subset, label):
        if not subset:
            return
        print(f"\n=== {label} (n={len(subset)}) ===")
        for cond in ("no_rag", "rag"):
            tcr = st.mean(tc[cond][t] for t in subset)
            pr = st.mean(prem_recall(comp[t][cond], [p["name"] for p in ev[t]["premises"]])
                         for t in subset)
            print(f"  {cond:7s}  typecheck={tcr:.3f}  premise_recall={pr:.3f}")
        d_tc = st.mean(tc["rag"][t] for t in subset) - st.mean(tc["no_rag"][t] for t in subset)
        d_pr = (st.mean(prem_recall(comp[t]["rag"], [p["name"] for p in ev[t]["premises"]]) for t in subset)
                - st.mean(prem_recall(comp[t]["no_rag"], [p["name"] for p in ev[t]["premises"]]) for t in subset))
        print(f"  RAG-noRAG delta: typecheck {d_tc:+.3f}  premise_recall {d_pr:+.3f}")

    agg(tids, "ALL")
    agg([t for t in tids if ev[t]["needs_rare"]], "needs_rare")
    agg([t for t in tids if not ev[t]["needs_rare"]], "no_rare")


if __name__ == "__main__":
    main()
