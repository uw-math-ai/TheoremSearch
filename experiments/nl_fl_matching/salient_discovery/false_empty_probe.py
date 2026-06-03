"""False-empty probe: re-run a sample of sweep empties at higher ann_k.

READ-ONLY. The sweep ran ann_k=50 (+max_scan_tuples=500k) and 41% of queries
returned 0 informal candidates. Some are genuinely non-matchable plumbing;
some are scan-horizon artifacts (§6 found ~20% rescued at ann_k=500). This
re-runs a random sample of empties at a larger ann_k and reports the rescue
rate (now-non-empty, and now-strong>=0.85).

Run on klone:
  cd /gscratch/amath/simku22/TheoremSearch && set -a; source .env; set +a
  export RDS_HOST=...; export PYTHONPATH=$PWD:$PWD/rds
  /gscratch/amath/simku22/salient_venv/bin/python \
    experiments/nl_fl_matching/salient_discovery/false_empty_probe.py \
    --glob '/gscratch/amath/simku22/salient_sweep/*.jsonl' \
    --manifest experiments/nl_fl_matching/salient_discovery/data/query_manifest_top50.csv \
    --n 40 --ann-k 500
"""
from __future__ import annotations
import argparse, csv, glob, json, random, sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT)); sys.path.insert(0, str(REPO_ROOT / "rds"))
from utils.connect import get_rds_connection            # noqa: E402
from experiments.nl_fl_matching import topk             # noqa: E402
from experiments.nl_fl_matching.pools import Stmt        # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--ann-k", type=int, default=500)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    empties = []
    for f in sorted(glob.glob(args.glob)):
        with open(f) as fh:
            for line in fh:
                line = line.strip()
                if not line: continue
                try: r = json.loads(line)
                except Exception: continue
                if r["n"] == 0:
                    empties.append((r["query_sid"], r["cls"], r["decl_name"]))
    print(f"empties total: {len(empties):,}", flush=True)

    man = {}
    with open(args.manifest) as fh:
        for row in csv.DictReader(fh):
            man[row["statement_id"]] = (row["paper_id"], row["slogan_id"], row["decl_name"], row["cls"])

    rng = random.Random(args.seed)
    samp = rng.sample([e for e in empties if e[0] in man], min(args.n, len(empties)))
    queries = [Stmt(sid, man[sid][0], man[sid][1], dec, "") for sid, cls, dec in samp]
    print(f"re-running {len(queries)} empties at ann_k={args.ann_k} (read-only)...", flush=True)

    conn = get_rds_connection("v2")
    with conn.cursor() as c: c.execute("SET default_transaction_read_only = on")
    conn.commit()

    rescued = strong = 0
    examples = []
    stream = topk.embedding_topk(conn, queries, candidate_pool="all_informals",
                                 k=10, ann_k=args.ann_k, exclusion="statement",
                                 embedding_model="qwen3-8b", show_progress=False)
    for q, res in zip(queries, stream):
        if res:
            rescued += 1
            s = res[0].similarity
            if s >= 0.85:
                strong += 1
                examples.append((s, q.name))
    stream.close(); conn.close()

    n = len(queries)
    print(f"\n=== false-empty probe (ann_k={args.ann_k}, n={n}) ===")
    print(f"  rescued (now non-empty): {rescued}/{n} ({100*rescued/n:.0f}%)   [§6 ~20%]")
    print(f"  rescued AND strong>=0.85: {strong}/{n} ({100*strong/n:.0f}%)")
    print(f"  => est. genuinely-non-matchable empties: ~{100*(n-rescued)/n:.0f}%")
    for s, name in sorted(examples, reverse=True)[:8]:
        print(f"     {s:.3f}  {name[:60]}")


if __name__ == "__main__":
    main()
