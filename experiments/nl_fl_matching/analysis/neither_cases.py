"""Sample and hydrate "neither" bucket pairs for failure-mode analysis.

A "neither" pair is a blueprint gold (informal, formal) that neither direction
recovered at rank 1. This script:

  1. Re-runs the agreement bucketing to get the neither set.
  2. Samples N pairs (default 15) by a chosen strategy.
  3. For each pair, fetches: gold informal slogan, gold formal slogan, gold
     formal decl_name, and the top-5 candidates each direction actually
     returned (with their slogans).
  4. Writes a CSV + a markdown report for paper inclusion.

Usage:
    python -m experiments.nl_fl_matching.analysis.neither_cases --n 15
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "rds"))

from utils.connect import get_rds_connection  # noqa: E402
from experiments.nl_fl_matching import gold  # noqa: E402
from experiments.nl_fl_matching.analysis.eval import fetch_rows  # noqa: E402
from experiments.nl_fl_matching.analysis.agreement import bucket_pairs  # noqa: E402


_HYDRATE_SQL = """
WITH q_slogan AS (
    SELECT DISTINCT ON (sl.statement_id) sl.statement_id, sl.slogan,
           sl.insufficient_context
      FROM slogan sl
     WHERE sl.statement_id = ANY(%(sids)s::uuid[])
       AND NOT sl.insufficient_context
     ORDER BY sl.statement_id, sl.created_at
)
SELECT st.statement_id::text,
       st.formality::text,
       st.kind,
       st.body,
       p.title       AS paper_title,
       p.external_id AS paper_external_id,
       fm.decl_name,
       fm.module,
       im.ref,
       im.lean       AS lean_annotation,
       sl.slogan
  FROM statement st
  JOIN paper p ON p.paper_id = st.paper_id
  LEFT JOIN formal_metadata   fm ON fm.statement_id   = st.statement_id
  LEFT JOIN informal_metadata im ON im.statement_id   = st.statement_id
  LEFT JOIN q_slogan          sl ON sl.statement_id   = st.statement_id
 WHERE st.statement_id = ANY(%(sids)s::uuid[])
"""


def hydrate(conn, sids):
    out = {}
    with conn.cursor() as cur:
        cur.execute(_HYDRATE_SQL, {"sids": [str(s) for s in sids]})
        cols = [d.name for d in cur.description]
        for row in cur.fetchall():
            rec = dict(zip(cols, row))
            out[rec["statement_id"]] = rec
    return out


def _short(s, n=200):
    if not s:
        return ""
    s = str(s).replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=15)
    p.add_argument("--seed", type=int, default=20260524)
    p.add_argument("--embedding-model", default="qwen3-8b")
    p.add_argument("--exclusion", default="statement")
    p.add_argument("--f2i-pool", default="gold_subset_f2i")
    p.add_argument("--i2f-pool", default="gold_subset_i2f")
    p.add_argument("--out-csv", type=Path,
                   default=REPO_ROOT / "experiments/nl_fl_matching/data/neither_cases.csv")
    p.add_argument("--out-md", type=Path,
                   default=REPO_ROOT / "experiments/nl_fl_matching/data/neither_cases.md")
    args = p.parse_args()

    rng = random.Random(args.seed)
    conn = get_rds_connection("v2")

    print("loading gold + ranks...", flush=True)
    g = gold.load_gold(conn, embedding_model=args.embedding_model)
    f2i = fetch_rows(conn, "f2i", args.embedding_model,
                     pool_descriptor=args.f2i_pool, exclusion=args.exclusion)
    i2f = fetch_rows(conn, "i2f", args.embedding_model,
                     pool_descriptor=args.i2f_pool, exclusion=args.exclusion)

    b = bucket_pairs(g.pairs, f2i, i2f,
                     g.formal_to_gold_informals, g.informal_to_gold_formals)
    print(f"  neither bucket: {len(b.neither):,}", flush=True)

    sample = rng.sample(b.neither, min(args.n, len(b.neither)))
    print(f"  sampling {len(sample)} pairs", flush=True)

    # Collect SIDs to hydrate: the gold pair + top-5 candidates each direction.
    all_sids = set()
    pair_topk = []
    for inf_sid, fml_sid in sample:
        f2i_top5 = [(r, cid, sim) for r, cid, sim in f2i.get(fml_sid, []) if r <= 5]
        i2f_top5 = [(r, cid, sim) for r, cid, sim in i2f.get(inf_sid, []) if r <= 5]
        all_sids.update([inf_sid, fml_sid])
        all_sids.update(cid for _, cid, _ in f2i_top5)
        all_sids.update(cid for _, cid, _ in i2f_top5)
        pair_topk.append((inf_sid, fml_sid, f2i_top5, i2f_top5))

    print(f"hydrating {len(all_sids):,} sids...", flush=True)
    info = hydrate(conn, all_sids)
    conn.close()

    # CSV: one row per (case_id, side, type, rank, sid, sim, slogan, ...)
    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.out_csv.open("w") as fh:
        w = csv.writer(fh, quoting=csv.QUOTE_ALL)
        w.writerow([
            "case", "row_type", "direction", "rank", "sid", "similarity",
            "formality", "kind", "paper_title", "decl_name_or_ref",
            "slogan", "body_short",
        ])
        for case_idx, (inf_sid, fml_sid, f2i_top5, i2f_top5) in enumerate(pair_topk):
            for side, sid in (("gold_informal", inf_sid), ("gold_formal", fml_sid)):
                r = info.get(sid, {})
                w.writerow([
                    case_idx, side, "", "", sid, "",
                    r.get("formality"), r.get("kind"), _short(r.get("paper_title"), 80),
                    r.get("decl_name") or _short(r.get("ref"), 60),
                    _short(r.get("slogan")), _short(r.get("body"), 240),
                ])
            for direction, top5 in (("f2i", f2i_top5), ("i2f", i2f_top5)):
                for rank, cid, sim in top5:
                    r = info.get(cid, {})
                    w.writerow([
                        case_idx, "topk_candidate", direction, rank, cid, f"{sim:.4f}",
                        r.get("formality"), r.get("kind"), _short(r.get("paper_title"), 80),
                        r.get("decl_name") or _short(r.get("ref"), 60),
                        _short(r.get("slogan")), _short(r.get("body"), 240),
                    ])
    print(f"wrote CSV → {args.out_csv.relative_to(REPO_ROOT)}", flush=True)

    # Markdown: human-readable side-by-side per case.
    with args.out_md.open("w") as fh:
        fh.write(f"# Neither-bucket failure cases (n={len(pair_topk)})\n\n")
        fh.write("Random sample of gold pairs that neither direction recovered at rank 1.\n")
        fh.write(f"Seed: {args.seed}. Source: `analysis/neither_cases.py`.\n\n")
        for case_idx, (inf_sid, fml_sid, f2i_top5, i2f_top5) in enumerate(pair_topk):
            inf = info.get(inf_sid, {})
            fml = info.get(fml_sid, {})
            fh.write(f"## Case {case_idx}\n\n")
            fh.write(f"**Gold informal** ({inf.get('paper_external_id')}, "
                     f"`{inf.get('ref')}`)\n\n")
            fh.write(f"> {_short(inf.get('slogan'), 400)}\n\n")
            fh.write(f"**Gold formal** ({fml.get('paper_external_id')}, "
                     f"`{fml.get('decl_name')}`)\n\n")
            fh.write(f"> {_short(fml.get('slogan'), 400)}\n\n")
            fh.write("**f→i top-5 (gold informal NOT in this list):**\n\n")
            for rank, cid, sim in f2i_top5:
                r = info.get(cid, {})
                fh.write(f"  {rank}. ({sim:.3f}) "
                         f"[{r.get('formality') or '?'}] "
                         f"`{r.get('decl_name') or r.get('ref')}` — "
                         f"{_short(r.get('slogan'), 180)}\n")
            fh.write("\n**i→f top-5 (gold formal NOT in this list):**\n\n")
            for rank, cid, sim in i2f_top5:
                r = info.get(cid, {})
                fh.write(f"  {rank}. ({sim:.3f}) "
                         f"[{r.get('formality') or '?'}] "
                         f"`{r.get('decl_name') or r.get('ref')}` — "
                         f"{_short(r.get('slogan'), 180)}\n")
            fh.write("\n---\n\n")
    print(f"wrote MD  → {args.out_md.relative_to(REPO_ROOT)}", flush=True)


if __name__ == "__main__":
    main()
