"""Per-node saliency feature matrix for the formal graph (Mathlib + projects).

READ-ONLY against RDS. Computes, for every formal declaration (388k), the
candidate "paper-worthiness" signals identified from the gold-set signature,
persists them to a local CSV (gitignored), and reports:

  - per-signal AUROC separating blueprint-gold (paper-worthy positives) from
    three negative sets (project-non-gold, Mathlib-all, all-non-gold)
  - the effect of a structural plumbing filter (compiler-generated / internal
    name patterns + typeclass instances + ultra-high in-degree)
  - a draft composite saliency score + its AUROC
  - a TRADEOFF curve: at descending saliency, (nodes kept, gold recall,
    %Mathlib kept) -- this is what lets the data (not a hand-picked N) decide
    the operating point.

The composite WEIGHTS here are a provisional draft; the literature-synthesis
workflow refines them. The FEATURE matrix is invariant to that.

Run:
    RDS_HOST=theorem-search.cluster-cx0ei6kq0qcn.us-west-2.rds.amazonaws.com \
        python3 experiments/nl_fl_matching/salient_discovery/saliency_features.py
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "rds"))

from utils.connect import get_rds_connection            # noqa: E402
from experiments.nl_fl_matching import gold              # noqa: E402

OUT_DIR = Path(__file__).parent / "data"
OUT_CSV = OUT_DIR / "saliency_features.csv"

# Heuristic mirror of lean-graph's shouldIncludeConstant(): compiler-generated /
# internal declarations that no paper discusses. The RDS formal_metadata set
# includes aux decls, so this catches the obvious machine-generated junk by name.
_AUTO_PAT = re.compile(
    r"(\._|"
    r"\.eq_\d+|\.eq_def|\.match_\d+|\.proof_\d+|\.fun_\d+|"
    r"\.rec$|\.recOn$|\.casesOn$|\.brecOn$|\.below$|\. brecOn|"
    r"\.binductionOn$|\.ind$|\.noConfusion|\.noConfusionType|\.ndrec|"
    r"\.injEq$|\.sizeOf_spec|\.sizeOf_eq|\.mk\.inj|\.toCtorIdx|\.ofNat|"
    r"\.fwd$|\.imp$)"
)
_AUX_SUFFIX = re.compile(r"(_aux\b|_aux_|_lemma\b|_helper|_internal|'$|_match_|_eq_def$)")


def is_compiler_gen(name: str) -> bool:
    if not name:
        return True
    if name.startswith("_"):
        return True
    return bool(_AUTO_PAT.search(name))


def has_aux_suffix(name: str) -> bool:
    return bool(name and _AUX_SUFFIX.search(name))


def rankdata_avg(a: np.ndarray) -> np.ndarray:
    """Average ranks (ties -> mean rank), numpy-only (no scipy dependency)."""
    a = np.asarray(a, dtype=np.float64)
    n = a.size
    order = np.argsort(a, kind="mergesort")
    sa = a[order]
    ranks_sorted = np.empty(n, dtype=np.float64)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and sa[j + 1] == sa[i]:
            j += 1
        ranks_sorted[i:j + 1] = (i + 1 + j + 1) / 2.0
        i = j + 1
    out = np.empty(n, dtype=np.float64)
    out[order] = ranks_sorted
    return out


def auroc(scores: np.ndarray, pos_mask: np.ndarray) -> float:
    """AUROC that `scores` ranks positives (pos_mask) above the rest."""
    npos = int(pos_mask.sum())
    nneg = int((~pos_mask).sum())
    if npos == 0 or nneg == 0:
        return float("nan")
    r = rankdata_avg(scores)
    return float((r[pos_mask].sum() - npos * (npos + 1) / 2.0) / (npos * nneg))


def main() -> None:
    conn = get_rds_connection("v2")
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SET default_transaction_read_only = on")     # hard read-only guard
    cur.execute("SET statement_timeout = '900000'")
    cur.execute("SHOW default_transaction_read_only")
    print("[guard] read_only =", cur.fetchone()[0], flush=True)

    def q(sql):
        cur.execute(sql)
        return cur.fetchall()

    print("[1] out-degree by edge_type (GROUP BY src_id, edge_type)...", flush=True)
    out_by_type: dict[str, dict[str, int]] = {}
    for sid, et, c in q("SELECT src_id::text, edge_type, count(*) "
                        "FROM formal_dependency GROUP BY src_id, edge_type"):
        out_by_type.setdefault(sid, {})[et] = c

    print("[2] in-degree (all + sig)...", flush=True)
    in_all = {sid: c for sid, c in q("SELECT dep_id::text, count(*) FROM formal_dependency GROUP BY dep_id")}
    in_sig = {sid: c for sid, c in q("SELECT dep_id::text, count(*) FROM formal_dependency WHERE edge_type='sig' GROUP BY dep_id")}

    print("[3] per-node metadata (388k)...", flush=True)
    rows = q("""
      SELECT s.statement_id::text, fm.decl_name, fm.module,
             COALESCE(length(btrim(fm.docstring)),0), fm.is_instance, s.kind,
             CASE WHEN p.external_id LIKE 'Mathlib_%' THEN 'mathlib'
                  WHEN p.external_id LIKE 'Batteries_%' THEN 'batteries' ELSE 'project' END
        FROM statement s JOIN formal_metadata fm ON fm.statement_id=s.statement_id
        JOIN paper p ON p.paper_id=s.paper_id WHERE p.source='Lean Repo'""")
    print(f"    {len(rows):,} formal nodes", flush=True)

    g = gold.load_gold(conn, embedding_model="qwen3-8b")
    gold_fml = {f.statement_id for f in g.formals}
    print(f"    gold formals: {len(gold_fml):,}", flush=True)
    conn.close()

    # ---- assemble feature matrix ----
    cols = ["statement_id", "cls", "is_gold", "kind", "is_instance",
            "out_all", "out_sig", "out_def", "out_proof", "in_all", "in_sig",
            "doclen", "has_doc", "nsdepth", "namelen", "compiler_gen", "aux_suffix"]
    feats = []
    for sid, decl, module, doclen, isinst, kind, cls in rows:
        ot = out_by_type.get(sid, {})
        feats.append(dict(
            statement_id=sid, cls=cls, is_gold=int(sid in gold_fml), kind=kind,
            is_instance=int(bool(isinst)),
            out_all=sum(ot.values()), out_sig=ot.get("sig", 0), out_def=ot.get("def", 0),
            out_proof=ot.get("proof", 0), in_all=in_all.get(sid, 0), in_sig=in_sig.get(sid, 0),
            doclen=doclen, has_doc=int(doclen > 0),
            nsdepth=(decl.count(".") if decl else 0), namelen=len(decl or ""),
            compiler_gen=int(is_compiler_gen(decl)), aux_suffix=int(has_aux_suffix(decl)),
        ))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(feats)
    print(f"[persist] {len(feats):,} rows -> {OUT_CSV}", flush=True)

    # ---- numpy views ----
    def arr(k):
        return np.array([f[k] for f in feats])
    is_gold = arr("is_gold").astype(bool)
    cls = np.array([f["cls"] for f in feats])
    out_all = arr("out_all").astype(float)
    in_alln = arr("in_all").astype(float)
    has_doc = arr("has_doc").astype(float)
    doclen = arr("doclen").astype(float)
    is_inst = arr("is_instance").astype(bool)
    comp_gen = arr("compiler_gen").astype(bool)
    aux = arr("aux_suffix").astype(bool)

    neg_sets = {
        "project_non_gold": (cls == "project") & ~is_gold,
        "mathlib_all":      (cls == "mathlib"),
        "all_non_gold":     ~is_gold,
    }

    def report_auroc(name, score):
        line = f"  {name:<22}"
        for nk, nmask in neg_sets.items():
            sel = is_gold | nmask
            a = auroc(score[sel], is_gold[sel])
            line += f"  {nk}={a:.3f}"
        print(line)

    print("\n=== per-signal AUROC (gold positives vs negative set) ===", flush=True)
    print("  (0.5=no separation, 1.0=perfect; higher score should = more salient)")
    report_auroc("log1p(out_all)", np.log1p(out_all))
    report_auroc("out_sig", arr("out_sig").astype(float))
    report_auroc("has_doc", has_doc)
    report_auroc("log1p(doclen)", np.log1p(doclen))
    report_auroc("-log1p(in_all)", -np.log1p(in_alln))
    report_auroc("not_instance", (~is_inst).astype(float))
    report_auroc("not_compiler_gen", (~comp_gen).astype(float))

    # ---- structural plumbing filter ----
    UBIQUITOUS_IN = 20000   # matches pipeline/generate_slogans/formal_prompt_utils.py precedent
    plumbing = comp_gen | is_inst | aux | (in_alln >= UBIQUITOUS_IN)
    kept = ~plumbing
    print("\n=== structural plumbing filter (compiler_gen | instance | aux | in>=20k) ===", flush=True)
    print(f"  flagged plumbing : {int(plumbing.sum()):,} / {len(feats):,} ({100*plumbing.mean():.1f}%)")
    print(f"  kept             : {int(kept.sum()):,}")
    print(f"  gold recall kept : {100*kept[is_gold].mean():.1f}%  (gold dropped: {int((~kept & is_gold).sum())})")
    for nk, nmask in (("mathlib", cls == "mathlib"), ("project", cls == "project")):
        print(f"  {nk} kept: {int((kept & nmask).sum()):,} / {int(nmask.sum()):,} ({100*(kept & nmask).mean()/max(nmask.mean(),1e-9):.1f}%)")

    # ---- draft composite saliency (provisional weights; refined post-literature) ----
    def z(x):
        x = np.asarray(x, float); s = x.std()
        return (x - x.mean()) / (s if s > 0 else 1.0)
    composite = z(np.log1p(out_all)) + 0.6 * z(np.log1p(doclen)) + 0.3 * has_doc
    composite = np.where(plumbing, -1e9, composite)   # exclude plumbing
    print("\n=== draft composite saliency AUROC ===", flush=True)
    report_auroc("composite(draft)", composite)

    # ---- TRADEOFF curve: descending saliency -> (nodes kept, gold recall, %mathlib kept) ----
    print("\n=== TRADEOFF: keep top-X% by composite saliency ===", flush=True)
    print(f"  {'keep%':>6} {'nodes':>9} {'gold_recall':>12} {'mathlib_kept':>13} {'project_kept':>13}")
    order = np.argsort(-composite)
    ng = int(is_gold.sum()); nm = int((cls == "mathlib").sum()); npj = int((cls == "project").sum())
    n = len(feats)
    for frac in (0.02, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50):
        k = int(n * frac)
        sel = np.zeros(n, bool); sel[order[:k]] = True
        gr = 100 * (sel & is_gold).sum() / max(ng, 1)
        mk = 100 * (sel & (cls == "mathlib")).sum() / max(nm, 1)
        pk = 100 * (sel & (cls == "project")).sum() / max(npj, 1)
        print(f"  {100*frac:>5.0f}% {k:>9,} {gr:>11.1f}% {mk:>12.1f}% {pk:>12.1f}%")
    print("\n[done]", flush=True)


if __name__ == "__main__":
    main()
