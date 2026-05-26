"""P1: build the statement-autoformalization eval set from held-out TEST targets.

For each sampled test target we need:
  - slogan      : the NL input the formalizer sees (from slogans.pkl)
  - gold_stmt   : the gold formal statement (statement.body = decl signature)
  - decl_name   : formal_metadata.decl_name
  - premises    : gold sig-premises, each {id, name, sig} (for RAG context + scoring)
  - rarity      : "needs_rare" if any gold premise has train-freq <= 3

Also reports statement.body coverage (we saw empties earlier) so we know the
gold is usable. Saves cache/formalization_eval.pkl.

Run:
    python scripts/build_formalization_eval.py
"""
import json
import os
import pickle
from pathlib import Path

import dotenv
dotenv.load_dotenv(os.environ.get("LPR_ENV_FILE", str(Path(__file__).resolve().parent.parent / ".env")))
import boto3
import numpy as np
import psycopg2

CACHE = Path(__file__).resolve().parent.parent / "cache"
SEED = 42
N_TARGETS = 1200   # oversample; only ~38% have a non-empty gold body


def connect():
    secret = json.loads(
        boto3.client("secretsmanager", region_name="us-west-2")
        .get_secret_value(SecretId=os.getenv("RDS_SECRET_ARN"))["SecretString"])
    return psycopg2.connect(
        host=os.getenv("RDS_HOST"), port=5432, dbname="v2",
        user=secret["username"], password=secret["password"], sslmode="require",
        connect_timeout=20, options="-c default_transaction_read_only=on -c statement_timeout=120000")


def main():
    targets = pickle.load(open(CACHE / "targets_full.pkl", "rb"))
    split = json.loads((CACHE / "split.json").read_text())
    freq = json.loads((CACHE / "premise_freq_train.json").read_text())
    slogans = pickle.load(open(CACHE / "slogans.pkl", "rb"))
    print(f"slogans loaded: {len(slogans):,}")

    rng = np.random.default_rng(SEED)
    test = [t for t, s in split.items() if s == "test" and t in slogans]
    rng.shuffle(test)
    sample = test[:N_TARGETS]
    print(f"sampled {len(sample)} test targets")

    # gather all statement_ids we need bodies/names for (targets + their premises)
    need = set(sample)
    for t in sample:
        need.update(targets[t]["gold"])
    need = list(need)
    print(f"pulling body+decl_name for {len(need):,} statements...")

    conn = connect()
    body = {}; name = {}
    B = 10000
    with conn.cursor() as c:
        for i in range(0, len(need), B):
            chunk = need[i:i + B]
            c.execute("SELECT statement_id::text, body FROM statement WHERE statement_id::text = ANY(%s)", (chunk,))
            for sid, b in c.fetchall():
                body[sid] = b or ""
            c.execute("SELECT statement_id::text, decl_name FROM formal_metadata WHERE statement_id::text = ANY(%s)", (chunk,))
            for sid, dn in c.fetchall():
                name[sid] = dn
    conn.close()

    # coverage diagnostics
    tgt_body_nonempty = sum(1 for t in sample if body.get(t, "").strip())
    all_body_nonempty = sum(1 for s in need if body.get(s, "").strip())
    print(f"\n=== body coverage ===")
    print(f"  targets w/ non-empty body: {tgt_body_nonempty}/{len(sample)}")
    print(f"  all stmts w/ non-empty body: {all_body_nonempty}/{len(need)}")
    print(f"  decl_name present: {sum(1 for s in need if name.get(s))}/{len(need)}")
    print("\n=== sample target ===")
    t0 = sample[0]
    print(f"  decl_name: {name.get(t0)}")
    print(f"  slogan:    {slogans[t0][:90]}")
    print(f"  gold_stmt: {body.get(t0,'')[:120]!r}")
    print(f"  #gold premises: {len(targets[t0]['gold'])}")
    g0 = targets[t0]['gold'][0]
    print(f"  premise[0]: {name.get(g0)}  sig={body.get(g0,'')[:80]!r}")

    # build eval records
    eval_set = {}
    for t in sample:
        gold = targets[t]["gold"]
        prem = [{"id": g, "name": name.get(g), "sig": body.get(g, "")} for g in gold]
        needs_rare = any(freq.get(g, 0) <= 3 for g in gold)
        eval_set[t] = {
            "slogan": slogans[t],
            "gold_stmt": body.get(t, ""),
            "decl_name": name.get(t),
            "n_gold": len(gold),
            "premises": prem,
            "needs_rare": needs_rare,
        }
    # only keep targets with a usable gold statement
    usable = {t: v for t, v in eval_set.items() if v["gold_stmt"].strip() and v["decl_name"]}
    print(f"\nusable eval targets (non-empty gold stmt + name): {len(usable)}/{len(sample)}")
    print(f"  needs_rare: {sum(v['needs_rare'] for v in usable.values())}/{len(usable)}")
    pickle.dump(usable, open(CACHE / "formalization_eval.pkl", "wb"))
    print(f"saved -> cache/formalization_eval.pkl")


if __name__ == "__main__":
    main()
