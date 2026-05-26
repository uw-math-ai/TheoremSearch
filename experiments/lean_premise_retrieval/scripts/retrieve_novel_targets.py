"""Retrieve premises for NOVEL (post-cutoff) targets whose own slogan is absent
from the corpus. Query = a back-translated informal embedding (ml_targets_qvecs.npy);
corpus = v2's v4.29-era formal slogan index. Applies the learned query head W,
returns top-k corpus decls, and scores recall of the gold sig-premises.

No forbidden masking needed: the v4.30 targets aren't in the v4.29 corpus, so the
premises we want are legitimately retrievable.

    python scripts/retrieve_novel_targets.py
"""
import json, sys
from pathlib import Path
import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.formal_retriever import FormalRetriever

CACHE = Path("/home/aurasl/projects/lean-repos/premise-rl/cache")
K = 15
KS = [10, 15, 50]


def main():
    targets = json.loads((CACHE / "ml_targets_informal.json").read_text())
    qvecs = np.load(CACHE / "ml_targets_qvecs.npy")            # [60, 4096] float32
    assert len(targets) == qvecs.shape[0]
    decl_name = json.loads((CACHE / "decl_names.json").read_text())  # sid -> name

    r = FormalRetriever(CACHE / "formal_emb.f16.npy", CACHE / "formal_ids.json")
    D = r.emb.shape[1]
    sd = torch.load(CACHE / "query_head_full.pt", map_location="cpu")
    Wm = next(v for v in sd.values() if v.ndim == 2 and v.shape == (D, D)).numpy().astype(np.float32)
    print(f"corpus={len(r.ids):,}  D={D}  head W={Wm.shape}")

    out = []
    rec = {("head", k): [] for k in KS}
    rec.update({("raw", k): [] for k in KS})
    maxk = max(KS)
    for t, q in zip(targets, qvecs):
        gold = set(t["premises"])
        q_head = q @ Wm.T
        hits_head = [decl_name.get(sid, sid) for sid, _ in r.search_by_vec(q_head, maxk)]
        hits_raw = [decl_name.get(sid, sid) for sid, _ in r.search_by_vec(q, maxk)]
        for k in KS:
            rec[("head", k)].append(len(gold & set(hits_head[:k])) / len(gold))
            rec[("raw", k)].append(len(gold & set(hits_raw[:k])) / len(gold))
        out.append({"name": t["name"], "module": t["module"], "informal": t["informal"],
                    "sig": t["sig"], "gold": sorted(gold),
                    "retrieved_head": hits_head[:K], "retrieved_raw": hits_raw[:K]})
    (CACHE / "ml_targets_retrieval.json").write_text(json.dumps(out))

    print("\n=== recall of gold sig-premises (n=%d targets) ===" % len(targets))
    print("  variant   " + "  ".join(f"R@{k}" for k in KS))
    for var in ("raw", "head"):
        cells = "  ".join(f"{np.mean(rec[(var, k)]):.3f}" for k in KS)
        print(f"  {var:<8}  {cells}")
    # how many targets have >=1 gold premise retrieved (the floor for RAG usefulness)
    anyhit = np.mean([1.0 if (set(o["gold"]) & set(o["retrieved_head"])) else 0.0 for o in out])
    print(f"\n  targets with >=1 gold in head top-{K}: {anyhit:.2f}")


if __name__ == "__main__":
    main()
