"""Gate + ordering-prior scorer -> query manifest for the broad sweep.

READ-ONLY. Applies the Layer-1 compiler-artifact GATE and computes a
transparent ORDERING prior (NOT the final calibrated score — learned weights
are fit in evaluation from sweep results). Emits an ordered manifest of
gate-surviving formal decls for the formal->informal sweep.

Ordering prior (hand-set, for sweep order + early-stop only; meaningful-match
precision comes from match cosine + the post-hoc calibrated score):
    prior = z(log1p(out_degree))            # proof/compositional depth (AUROC 0.79)
          + z(doc_cohortnorm)               # docstring presence minus library base rate
          + 0.5*z(kind_prior)               # theorem/def high; struct/class lowered (§6a)
          - z(glue_penalty)                 # instance-no-doc | extreme in-degree tail | glue-suffix-no-doc

Gate (verified 100% gold recall; drops ~0.65% compiler artifacts):
  norm_kind in whitelist (drops constructor/ctor) AND NOT compiler-internal name.

Reuses the per-node features in data/saliency_features.csv; pulls only the
3 fields the sweep needs (paper_id, slogan_id, decl_name) from RDS read-only.

Run:
  RDS_HOST=theorem-search.cluster-cx0ei6kq0qcn.us-west-2.rds.amazonaws.com \
    python3 experiments/nl_fl_matching/salient_discovery/saliency_prior.py
Output: data/query_manifest.csv  (statement_id,paper_id,slogan_id,cls,kind,decl_name,prior) sorted prior desc.
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

HERE = Path(__file__).parent
FEAT_CSV = HERE / "data" / "saliency_features.csv"
OUT_CSV = HERE / "data" / "query_manifest.csv"

KIND_NORM = {"thm": "theorem", "def": "definition", "inst": "instance",
             "struct": "structure", "ctor": "constructor", "ind": "inductive"}
GATE_KINDS = {"theorem", "definition", "instance", "structure", "class",
              "inductive", "opaque", "axiom"}
KIND_PRIOR = {"theorem": 1.0, "definition": 1.0, "inductive": 0.9, "opaque": 0.7,
              "axiom": 0.7, "instance": 0.5, "structure": 0.4, "class": 0.4}

# Narrowed compiler-internal name patterns (verified 0 gold cost; does NOT
# include the over-matching numeric/eq_/bare-recursor rules — see README).
_INTERNAL = re.compile(r"(^|\.)_")
_INTERNAL_FINAL = re.compile(r"\.(match_|proof_)[^.]*$")
_INTERNAL_SUFFIX = re.compile(r"\.(injEq|sizeOf_spec|noConfusion|brecOn|ndrec|toCtorIdx)(\.|$)")
_GLUE_SUFFIX = re.compile(r"_(comm|assoc|zero|one|left|right|self|neg|inv|add|mul)$")


def is_compiler_internal(name: str) -> bool:
    if not name:
        return True
    return bool(_INTERNAL.search(name) or _INTERNAL_FINAL.search(name) or _INTERNAL_SUFFIX.search(name))


def z(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, float); s = x.std()
    return (x - x.mean()) / (s if s > 0 else 1.0)


def main() -> None:
    # --- read-only pull of the 3 sweep fields + decl_name for the gate ---
    conn = get_rds_connection("v2"); conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SET default_transaction_read_only = on")
    cur.execute("SET statement_timeout = '900000'")
    print("[guard] read_only =", (cur.execute("SHOW default_transaction_read_only"), cur.fetchone()[0])[1], flush=True)
    print("[pull] statement_id, paper_id, slogan_id (qwen3-8b-embedded), decl_name ...", flush=True)
    cur.execute("""
      SELECT DISTINCT ON (st.statement_id)
             st.statement_id::text, st.paper_id::text, sl.slogan_id::text, fm.decl_name
        FROM statement st
        JOIN paper p        ON p.paper_id = st.paper_id
        JOIN formal_metadata fm ON fm.statement_id = st.statement_id
        JOIN slogan sl      ON sl.statement_id = st.statement_id
        JOIN embedding e    ON e.slogan_id = sl.slogan_id
       WHERE p.source = 'Lean Repo'
         AND sl.model_name = 'qwen3-235b' AND NOT sl.insufficient_context
         AND e.model_name = 'qwen3-8b'
       ORDER BY st.statement_id, sl.created_at
    """)
    pull = {sid: (pid, slid, decl) for sid, pid, slid, decl in cur.fetchall()}
    conn.close()
    print(f"[pull] {len(pull):,} embeddable formal nodes", flush=True)

    # --- merge with feature CSV ---
    feats = list(csv.DictReader(FEAT_CSV.open()))
    recs = []
    for r in feats:
        sid = r["statement_id"]
        if sid not in pull:
            continue  # not embeddable -> can't be a sweep query
        pid, slid, decl = pull[sid]
        nkind = KIND_NORM.get(r["kind"], r["kind"])
        recs.append(dict(
            statement_id=sid, paper_id=pid, slogan_id=slid, decl_name=decl or "",
            cls=r["cls"], nkind=nkind, is_gold=int(r["is_gold"]),
            out_all=float(r["out_all"]), in_sig=float(r["in_sig"]),
            has_doc=int(r["has_doc"]), is_instance=int(r["is_instance"]),
        ))
    print(f"[merge] {len(recs):,} nodes with features + embedding", flush=True)

    # --- GATE ---
    gated = [x for x in recs
             if x["nkind"] in GATE_KINDS and not is_compiler_internal(x["decl_name"])]
    ng_total = sum(x["is_gold"] for x in recs)
    ng_kept = sum(x["is_gold"] for x in gated)
    print(f"[gate] survivors {len(gated):,} / {len(recs):,} "
          f"(dropped {len(recs)-len(gated):,}); gold recall {100*ng_kept/max(ng_total,1):.2f}% "
          f"({ng_kept}/{ng_total})", flush=True)

    # --- ordering prior over survivors ---
    cls = np.array([x["cls"] for x in gated])
    has_doc = np.array([x["has_doc"] for x in gated], float)
    out_all = np.array([x["out_all"] for x in gated], float)
    in_sig = np.array([x["in_sig"] for x in gated], float)
    is_inst = np.array([x["is_instance"] for x in gated], bool)
    glue = np.array([1.0 if _GLUE_SUFFIX.search(x["decl_name"]) else 0.0 for x in gated])
    mu = {c: has_doc[cls == c].mean() if (cls == c).any() else 0.0 for c in set(cls)}
    doc_cohort = np.array([has_doc[i] - mu[cls[i]] for i in range(len(gated))])
    kind_prior = np.array([KIND_PRIOR.get(x["nkind"], 0.5) for x in gated])
    tail = np.quantile(in_sig, 0.995)
    glue_pen = (0.5 * (is_inst & (has_doc == 0)).astype(float)
                + 0.5 * (in_sig >= tail).astype(float)
                + 0.3 * ((glue == 1) & (has_doc == 0)).astype(float))

    prior = (z(np.log1p(out_all)) + z(doc_cohort) + 0.5 * z(kind_prior) - z(glue_pen))
    order = np.argsort(-prior)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["statement_id", "paper_id", "slogan_id", "cls", "kind", "decl_name", "prior"])
        for i in order:
            x = gated[i]
            w.writerow([x["statement_id"], x["paper_id"], x["slogan_id"], x["cls"],
                        x["nkind"], x["decl_name"], f"{prior[i]:.4f}"])
    print(f"[manifest] {len(gated):,} rows -> {OUT_CSV}", flush=True)

    # --- summary ---
    gold_arr = np.array([x["is_gold"] for x in gated], bool)
    ranks_of_gold = np.argsort(np.argsort(-prior))[gold_arr]
    print(f"[order] gold median sweep-rank = {int(np.median(ranks_of_gold)):,} of {len(gated):,} "
          f"(gold in top-25%: {100*np.mean(ranks_of_gold < len(gated)*0.25):.0f}%)", flush=True)
    print("[order] top-5 by prior:", flush=True)
    for i in order[:5]:
        print(f"    {prior[i]:+.2f} [{gated[i]['cls']}/{gated[i]['nkind']}] {gated[i]['decl_name']}")
    print("[order] bottom-3 by prior:", flush=True)
    for i in order[-3:]:
        print(f"    {prior[i]:+.2f} [{gated[i]['cls']}/{gated[i]['nkind']}] {gated[i]['decl_name']}")
    print("[done]", flush=True)


if __name__ == "__main__":
    main()
