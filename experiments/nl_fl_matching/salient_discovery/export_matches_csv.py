"""Export sweep matches to a human-readable CSV for eye-checking.

READ-ONLY. For each formal query whose rank-1 informal match has sim>=min,
emits a row with formal + informal slogans/bodies/metadata side-by-side,
sorted by similarity desc. Columns put the two slogans adjacent for fast
visual comparison.

Run on klone:
  cd /gscratch/amath/simku22/TheoremSearch && set -a; source .env; set +a
  export RDS_HOST=...; export PYTHONPATH=$PWD:$PWD/rds
  /gscratch/amath/simku22/salient_venv/bin/python \
    experiments/nl_fl_matching/salient_discovery/export_matches_csv.py \
    --glob '/gscratch/amath/simku22/salient_sweep/*.jsonl' \
    --min-sim 0.85 --out /gscratch/amath/simku22/salient_matches.csv
"""
from __future__ import annotations
import argparse, csv, glob, json, sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT)); sys.path.insert(0, str(REPO_ROOT / "rds"))


def band(s):
    return "0.95-1.0" if s >= 0.95 else "0.90-0.95" if s >= 0.90 else "0.85-0.90" if s >= 0.85 else "0.75-0.85"


def clean(s, n):
    if not s: return ""
    return " ".join(str(s).split())[:n]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-sim", type=float, default=0.85)
    ap.add_argument("--max-body", type=int, default=1200)
    args = ap.parse_args()

    rows = []
    for f in sorted(glob.glob(args.glob)):
        with open(f) as fh:
            for line in fh:
                line = line.strip()
                if not line: continue
                try: r = json.loads(line)
                except Exception: continue
                if not r["n"]: continue
                t = r["results"][0]
                if t["sim"] >= args.min_sim:
                    rows.append({"sim": t["sim"], "cls": r["cls"], "query_sid": r["query_sid"],
                                 "formal_decl": r["decl_name"], "cand_sid": t["cand_sid"], "cand_pid": t["cand_pid"]})
    print(f"rank-1 matches sim>={args.min_sim}: {len(rows):,}", flush=True)

    from utils.connect import get_rds_connection
    conn = get_rds_connection("v2"); conn.autocommit = True
    cur = conn.cursor(); cur.execute("SET default_transaction_read_only = on")

    fsids = list({r["query_sid"] for r in rows})
    csids = list({r["cand_sid"] for r in rows})
    cpids = list({r["cand_pid"] for r in rows})

    def batched(sids, sql):
        out = {}
        for i in range(0, len(sids), 5000):
            cur.execute(sql, (sids[i:i+5000],))
            for row in cur.fetchall():
                out[row[0]] = row[1:]
        return out

    print("hydrating formal metadata + slogans + bodies...", flush=True)
    fmeta = batched(fsids, "SELECT statement_id::text, decl_name, module FROM formal_metadata WHERE statement_id=ANY(%s::uuid[])")
    fbody = batched(fsids, "SELECT statement_id::text, body FROM statement WHERE statement_id=ANY(%s::uuid[])")
    print("hydrating informal metadata + slogans + bodies...", flush=True)
    ibody = batched(csids, "SELECT statement_id::text, body FROM statement WHERE statement_id=ANY(%s::uuid[])")
    iref = batched(csids, "SELECT statement_id::text, COALESCE(ref,label,'') FROM informal_metadata WHERE statement_id=ANY(%s::uuid[])")
    pmeta = batched(cpids, "SELECT paper_id::text, source, external_id, title FROM paper WHERE paper_id=ANY(%s::uuid[])")

    # slogans (qwen3-235b) for both sides in one query
    allsids = fsids + csids
    slog = {}
    for i in range(0, len(allsids), 5000):
        cur.execute("""SELECT DISTINCT ON (statement_id) statement_id::text, slogan FROM slogan
                       WHERE statement_id=ANY(%s::uuid[]) AND model_name='qwen3-235b' AND NOT insufficient_context
                       ORDER BY statement_id, created_at""", (allsids[i:i+5000],))
        for sid, sl in cur.fetchall(): slog[sid] = sl
    conn.close()

    rows.sort(key=lambda r: -r["sim"])
    cols = ["sim", "band", "cls", "formal_decl", "formal_slogan", "informal_slogan",
            "informal_source", "arxiv_id", "paper_title", "informal_ref",
            "formal_module", "formal_body", "informal_body", "query_sid", "cand_sid"]
    with open(args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader()
        for r in rows:
            fm = fmeta.get(r["query_sid"], ("", "")); pm = pmeta.get(r["cand_pid"], ("", "", ""))
            w.writerow({
                "sim": f"{r['sim']:.4f}", "band": band(r["sim"]), "cls": r["cls"],
                "formal_decl": r["formal_decl"],
                "formal_slogan": clean(slog.get(r["query_sid"], ""), 600),
                "informal_slogan": clean(slog.get(r["cand_sid"], ""), 600),
                "informal_source": pm[0] or "", "arxiv_id": pm[1] or "",
                "paper_title": clean(pm[2], 200), "informal_ref": clean(iref.get(r["cand_sid"], ("",))[0], 60),
                "formal_module": fm[1] if len(fm) > 1 else "",
                "formal_body": clean(fbody.get(r["query_sid"], ("",))[0], args.max_body),
                "informal_body": clean(ibody.get(r["cand_sid"], ("",))[0], args.max_body),
                "query_sid": r["query_sid"], "cand_sid": r["cand_sid"],
            })
    print(f"wrote {len(rows):,} rows -> {args.out}", flush=True)


if __name__ == "__main__":
    main()
