"""Build a body-parity, fixed-seed RANDOM per-tier sample + representativeness check.

For each 0.1-width similarity tier, enumerate the COMPLETE population from the
sweep shards, draw N uniformly with a fixed seed, hydrate content from RDS, and
backfill the formal Lean signature from the corrected v3 DB (so judging sees
source -- the bias we proved matters). Then print POPULATION vs SAMPLE on
sim / project / source / body-coverage so skew is visible BEFORE any judging.

NO judging here -- pure data. READ-ONLY over RDS + corrected DB.
Run on klone (set RDS_HOST, PYTHONPATH, source .env).
"""
from __future__ import annotations
import argparse, csv, glob, json, random, sqlite3, sys
from pathlib import Path
from collections import Counter

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT)); sys.path.insert(0, str(REPO_ROOT / "rds"))

BASE = "/gscratch/amath/simku22"
CORPUS_DB = f"{BASE}/corpus_v3_fixed/corpus_v3 (corrected ingestion order).db"
CORE = {"Init", "Batteries", "Std", "Lean"}
# (label, lo, hi) half-open
TIERS = [("0.90-1.0", 0.90, 1.0001), ("0.80-0.90", 0.80, 0.90),
         ("0.70-0.80", 0.70, 0.80), ("0.60-0.70", 0.60, 0.70),
         ("0.50-0.60", 0.50, 0.60)]


def proj(module):
    p = (module or "").split(".")[0] or "(unknown)"
    return p


def cls3(module):
    p = proj(module)
    return "Mathlib" if p == "Mathlib" else ("CoreLean" if p in CORE else "Project")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", action="append", required=True)
    ap.add_argument("--out", default=f"{BASE}/tier_sample.csv")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-body", type=int, default=1200)
    args = ap.parse_args()

    # 1) enumerate COMPLETE population per tier from all shards
    files = []
    for g in args.glob:
        files.extend(sorted(glob.glob(g)))
    pop = {label: [] for label, _, _ in TIERS}
    for f in files:
        for line in open(f):
            line = line.strip()
            if not line:
                continue
            try: r = json.loads(line)
            except Exception: continue
            if not r["n"]:
                continue
            t = r["results"][0]; s = t["sim"]
            for label, lo, hi in TIERS:
                if lo <= s < hi:
                    pop[label].append({"sim": s, "cls": r["cls"], "query_sid": r["query_sid"],
                                       "formal_decl": r["decl_name"], "cand_sid": t["cand_sid"],
                                       "cand_pid": t["cand_pid"], "band": label})
                    break
    for label, _, _ in TIERS:
        print(f"population {label}: {len(pop[label]):,}", flush=True)

    # 2) fixed-seed uniform draw per tier
    rng = random.Random(args.seed)
    sample = {}
    for label, _, _ in TIERS:
        pool = pop[label]
        sample[label] = pool if len(pool) <= args.n else rng.sample(pool, args.n)
    rows = [r for label, _, _ in TIERS for r in sample[label]]
    print(f"sampled total: {len(rows)} (seed={args.seed})", flush=True)

    # 3) signatures from corrected DB (for body parity) + module for project tagging
    c = sqlite3.connect(f"file:{CORPUS_DB}?mode=ro&immutable=1", uri=True)
    sig = {n: s for n, s in c.execute("SELECT full_name, signature FROM nodes WHERE length(COALESCE(signature,''))>0")}
    modmap = {n: m for n, m in c.execute("SELECT full_name, module FROM nodes")}
    c.close()

    # 4) hydrate slogans / informal body / paper meta from RDS for the SAMPLE only
    from utils.connect import get_rds_connection
    conn = get_rds_connection("v2"); conn.autocommit = True
    cur = conn.cursor(); cur.execute("SET default_transaction_read_only = on")
    csids = list({r["cand_sid"] for r in rows}); cpids = list({r["cand_pid"] for r in rows})
    fsids = list({r["query_sid"] for r in rows})

    def batched(sids, sql):
        out = {}
        for i in range(0, len(sids), 5000):
            cur.execute(sql, (sids[i:i+5000],))
            for row in cur.fetchall():
                out[row[0]] = row[1:]
        return out

    fmod = batched(fsids, "SELECT statement_id::text, module FROM formal_metadata WHERE statement_id=ANY(%s::uuid[])")
    ibody = batched(csids, "SELECT statement_id::text, body FROM statement WHERE statement_id=ANY(%s::uuid[])")
    iref = batched(csids, "SELECT statement_id::text, COALESCE(ref,label,'') FROM informal_metadata WHERE statement_id=ANY(%s::uuid[])")
    pmeta = batched(cpids, "SELECT paper_id::text, source, external_id, title FROM paper WHERE paper_id=ANY(%s::uuid[])")
    allsids = fsids + csids; slog = {}
    for i in range(0, len(allsids), 5000):
        cur.execute("""SELECT DISTINCT ON (statement_id) statement_id::text, slogan FROM slogan
                       WHERE statement_id=ANY(%s::uuid[]) AND model_name='qwen3-235b' AND NOT insufficient_context
                       ORDER BY statement_id, created_at""", (allsids[i:i+5000],))
        for sid, sl in cur.fetchall(): slog[sid] = sl
    conn.close()

    def clean(s, n):
        return " ".join(str(s or "").split())[:n]

    # 5) write the content CSV (body backfilled from signature)
    cols = ["sim", "band", "cls", "formal_decl", "formal_slogan", "informal_slogan",
            "informal_source", "arxiv_id", "paper_title", "informal_ref",
            "formal_module", "formal_body", "informal_body", "query_sid", "cand_sid"]
    for r in rows:
        r["_module"] = modmap.get(r["formal_decl"]) or (fmod.get(r["query_sid"], ("",))[0] or "")
        r["_body"] = sig.get(r["formal_decl"], "")
    with open(args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader()
        for r in rows:
            pm = pmeta.get(r["cand_pid"], ("", "", ""))
            src = pm[0] or ""
            w.writerow({
                "sim": f"{r['sim']:.4f}", "band": r["band"], "cls": r["cls"],
                "formal_decl": r["formal_decl"],
                "formal_slogan": clean(slog.get(r["query_sid"], ""), 600),
                "informal_slogan": clean(slog.get(r["cand_sid"], ""), 600),
                "informal_source": src, "arxiv_id": pm[1] or "",
                "paper_title": clean(pm[2], 200), "informal_ref": clean(iref.get(r["cand_sid"], ("",))[0], 60),
                "formal_module": r["_module"],
                "formal_body": clean(r["_body"], args.max_body),
                "informal_body": clean(ibody.get(r["cand_sid"], ("",))[0], args.max_body),
                "query_sid": r["query_sid"], "cand_sid": r["cand_sid"],
            })

    # 6) REPRESENTATIVENESS CHECK: population vs sample per tier (gate before judging)
    def src3(p):  # paper source bucket -- need module for project; use cand source string
        return p
    def describe(items, body_lookup, mod_lookup):
        n = len(items)
        sims = [it["sim"] for it in items]
        mean = sum(sims) / n
        med = sorted(sims)[n // 2]
        comp = Counter(cls3(mod_lookup(it)) for it in items)
        bodied = sum(1 for it in items if body_lookup(it))
        return n, mean, med, comp, bodied

    # population lacks RDS module; tag via corrected-DB modmap (covers 99%+)
    def pop_mod(it): return modmap.get(it["formal_decl"], "")
    def pop_body(it): return bool(sig.get(it["formal_decl"]))
    def samp_mod(it): return it["_module"]
    def samp_body(it): return bool(it["_body"])

    print("\n=== REPRESENTATIVENESS: population vs sample (gate BEFORE judging) ===")
    for label, _, _ in TIERS:
        P = pop[label]; S = sample[label]
        if not P:
            print(f"\n{label}: EMPTY population"); continue
        pn, pmean, pmed, pcomp, pbod = describe(P, pop_body, pop_mod)
        sn, smean, smed, scomp, sbod = describe(S, samp_body, samp_mod)
        print(f"\n{label}   population n={pn:,}   sample n={sn}")
        print(f"  mean sim     {pmean:.3f}   {smean:.3f}")
        print(f"  median sim   {pmed:.3f}   {smed:.3f}")
        for k in ("Mathlib", "CoreLean", "Project"):
            print(f"  {k:9}    {100*pcomp[k]/pn:5.1f}%   {100*scomp[k]/sn:5.1f}%")
        print(f"  has body     {100*pbod/pn:5.1f}%   {100*sbod/sn:5.1f}%   <-- PARITY GUARD")
    print(f"\nwrote sample content -> {args.out}")
    # save the drawn keys for audit/repro
    with open(args.out.replace(".csv", "_keys.json"), "w") as fh:
        json.dump({lab: [f'{r["query_sid"]}|{r["cand_sid"]}' for r in sample[lab]] for lab, _, _ in TIERS}, fh)
    print(f"wrote drawn keys -> {args.out.replace('.csv','_keys.json')}")


if __name__ == "__main__":
    main()
