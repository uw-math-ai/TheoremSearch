"""Backfill recovered Lean signatures + build the paired empty-body re-judge arms.

Runs on klone (reads the corrected corpus DB + existing content/consensus).
Signatures recovered from the v3 *corrected ingestion order* DB (full_name->signature),
which has source for 99.1% of nodes (the RDS-loaded DB lost 47% to an ingestion-order bug).

Outputs (all under /gscratch/amath/simku22):
  salient_matches_full_bodied.csv  -- all >=0.85 rows, formal_body backfilled where empty
  rejudge_control.csv              -- 150 empty-body MATCHES, formal_body="" (slogan-only control)
  rejudge_treat.csv                -- same 150, formal_body=recovered signature (treatment)

Paired design: Arm A (control) isolates judge stochastic flip; Arm B (treat) adds source.
B-vs-A difference = the causal effect of the Lean source on verdicts.
"""
from __future__ import annotations
import csv, json, random, sqlite3

BASE = "/gscratch/amath/simku22"
CORPUS_DB = f"{BASE}/corpus_v3_fixed/corpus_v3 (corrected ingestion order).db"
CONTENT = f"{BASE}/salient_matches_full.csv"
CONSENSUS = f"{BASE}/consensus_ge90_v2_all.jsonl"
N = 150
SEED = 0

csv.field_size_limit(10_000_000)


def empty(v):
    return not (v or "").strip()


def main():
    # 1) full_name -> signature from the corrected DB
    c = sqlite3.connect(f"file:{CORPUS_DB}?mode=ro&immutable=1", uri=True)
    sig = {}
    for name, s in c.execute("SELECT full_name, signature FROM nodes WHERE length(COALESCE(signature,''))>0"):
        sig[name] = s
    c.close()
    print(f"signatures loaded: {len(sig):,}", flush=True)

    # 2) load content (>=0.85) and backfill formal_body where empty
    rows = list(csv.DictReader(open(CONTENT)))
    cols = rows[0].keys()
    backfilled = 0
    for r in rows:
        if empty(r.get("formal_body", "")):
            s = sig.get(r["formal_decl"])
            if s:
                r["formal_body"] = " ".join(s.split())[:1200]
                backfilled += 1
    print(f"content rows: {len(rows):,}  backfilled bodies: {backfilled:,}", flush=True)
    with open(f"{BASE}/salient_matches_full_bodied.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(cols)); w.writeheader(); w.writerows(rows)
    print(f"wrote salient_matches_full_bodied.csv", flush=True)

    # 3) sample 150 empty-body MATCHES (edge==True in consensus, body empty in ORIGINAL content)
    by_key = {f'{r["query_sid"]}|{r["cand_sid"]}': r for r in rows}
    orig_empty = {f'{r["query_sid"]}|{r["cand_sid"]}' for r in csv.DictReader(open(CONTENT))
                  if empty(r.get("formal_body", ""))}
    match_keys = []
    for l in open(CONSENSUS):
        l = l.strip()
        if not l:
            continue
        c = json.loads(l)
        if c["edge"] is True and c["key"] in orig_empty and c["key"] in by_key:
            sg = sig.get(by_key[c["key"]]["formal_decl"])
            if sg:  # only edges we can actually recover a signature for
                match_keys.append(c["key"])
    rng = random.Random(SEED)
    sample = match_keys if len(match_keys) <= N else rng.sample(match_keys, N)
    print(f"empty-body recoverable matches: {len(match_keys):,}  sampled: {len(sample)}", flush=True)

    def write_arm(path, with_body):
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(cols)); w.writeheader()
            for k in sample:
                r = dict(by_key[k])
                if with_body:
                    r["formal_body"] = " ".join(sig[r["formal_decl"]].split())[:1200]
                else:
                    r["formal_body"] = ""
                w.writerow(r)
    write_arm(f"{BASE}/rejudge_control.csv", with_body=False)
    write_arm(f"{BASE}/rejudge_treat.csv", with_body=True)
    print("wrote rejudge_control.csv (slogan-only) + rejudge_treat.csv (with signature)", flush=True)


if __name__ == "__main__":
    main()
