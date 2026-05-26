"""Build the module-held-out three-way split for the formal premise-retrieval
experiment, plus the frequency tables the prior baseline and rarity
stratification need. Run once; everything downstream (prior, supervised, RL)
evaluates on this frozen split.

Gold premise = formal_dependency edge of type sig/extends/field (the deps of a
statement's *signature* — what you need to state it, not prove it). proof/def
edges are excluded.

Held-out unit = `module` (formal_metadata.module, the Lean file). Whole modules
go to train/val/test (~80/10/10 by target count), so a theorem and its
file-mates never straddle the split — the central leakage control.

Outputs (cache/):
  targets_full.pkl        {tid: {"gold": [dep_id,...], "module": str}}
  split.json              {tid: "train"|"val"|"test"}
  premise_freq_train.json {dep_id: # train targets it is gold for}  (prior + rarity)

Run:
    python scripts/build_split.py
"""
import json
import os
import pickle
import time
from collections import defaultdict
from pathlib import Path

import dotenv
dotenv.load_dotenv(os.environ.get("LPR_ENV_FILE", str(Path(__file__).resolve().parent.parent / ".env")))
import boto3
import psycopg2

CACHE = Path(__file__).resolve().parent.parent / "cache"
GOLD_TYPES = ("sig", "extends", "field")
SEED = 42
MIN_GOLD = 2


def connect():
    secret = json.loads(
        boto3.client("secretsmanager", region_name="us-west-2")
        .get_secret_value(SecretId=os.getenv("RDS_SECRET_ARN"))["SecretString"])
    return psycopg2.connect(
        host=os.getenv("RDS_HOST"), port=5432, dbname="v2",
        user=secret["username"], password=secret["password"], sslmode="require",
        connect_timeout=20,
        options="-c default_transaction_read_only=on -c statement_timeout=0")


def main():
    conn = connect()
    t0 = time.time()

    # 1) module per statement (the held-out key)
    print(f"[{time.strftime('%H:%M:%S')}] pulling module map...")
    with conn.cursor() as c:
        c.execute("SELECT statement_id::text, module FROM formal_metadata")
        module_of = {sid: mod for sid, mod in c.fetchall()}
    print(f"  modules: {len(module_of):,}")

    # 2) gold edges (sig/extends/field), grouped by src — streamed
    print(f"[{time.strftime('%H:%M:%S')}] streaming gold edges {GOLD_TYPES}...")
    gold = defaultdict(set)
    cur = conn.cursor(name="gold_edges")
    cur.itersize = 50000
    cur.execute(
        "SELECT src_id::text, dep_id::text FROM formal_dependency "
        "WHERE edge_type = ANY(%s)", (list(GOLD_TYPES),))
    n = 0
    for src, dep in cur:
        gold[src].add(dep)
        n += 1
        if n % 1_000_000 == 0:
            print(f"  {n:,} edges  ({n/(time.time()-t0):.0f}/s)")
    cur.close()
    conn.close()
    print(f"  total gold edges: {n:,}   srcs with >=1: {len(gold):,}")

    # 3) qualifying targets: >=MIN_GOLD gold deps, target+deps have module (=> in corpus)
    targets = {}
    for tid, deps in gold.items():
        if tid not in module_of:
            continue
        deps = {d for d in deps if d in module_of and d != tid}  # drop self + uncovered
        if len(deps) >= MIN_GOLD:
            targets[tid] = {"gold": sorted(deps), "module": module_of[tid]}
    print(f"  qualifying targets (>= {MIN_GOLD} gold): {len(targets):,}")

    # 4) module-held-out 3-way split (~80/10/10 by target count)
    by_mod = defaultdict(list)
    for tid, meta in targets.items():
        by_mod[meta["module"]].append(tid)
    mods = sorted(by_mod)
    import random
    random.Random(SEED).shuffle(mods)
    N = len(targets)
    split = {}
    acc = 0
    for m in mods:
        frac = acc / N
        s = "test" if frac < 0.10 else "val" if frac < 0.20 else "train"
        for tid in by_mod[m]:
            split[tid] = s
        acc += len(by_mod[m])
    from collections import Counter
    cnt = Counter(split.values())
    print(f"  split (by module, {len(mods):,} modules): {dict(cnt)}")

    # 5) premise frequency over TRAIN targets only (no leakage into prior)
    freq = defaultdict(int)
    for tid, meta in targets.items():
        if split[tid] == "train":
            for d in meta["gold"]:
                freq[d] += 1

    CACHE.mkdir(exist_ok=True)
    pickle.dump(targets, open(CACHE / "targets_full.pkl", "wb"))
    (CACHE / "split.json").write_text(json.dumps(split))
    (CACHE / "premise_freq_train.json").write_text(json.dumps(dict(freq)))
    # full gold adjacency (src -> [gold deps]) so downstream evals can derive
    # forbidden(F) = {F} ∪ transitive reverse-deps(F) without re-querying v2.
    pickle.dump({s: sorted(ds) for s, ds in gold.items()}, open(CACHE / "gold_edges.pkl", "wb"))
    print(f"[{time.strftime('%H:%M:%S')}] saved targets_full.pkl, split.json, "
          f"premise_freq_train.json, gold_edges.pkl  ({time.time()-t0:.0f}s total)")


if __name__ == "__main__":
    main()
