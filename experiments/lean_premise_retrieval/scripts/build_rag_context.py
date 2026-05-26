"""P2: build the retrieval context for each formalization-eval target.

Query = the target's own slogan embedding (already in the index), passed
through the learned query head. Retrieve top-K premises -> their decl_names.
Those names are the RAG context the formalizer gets: "to state this, you likely
need: <names>". Names are the core grounding signal and are 100% available.

Also reports retrieval recall@K on this eval subset (rare vs common) so we know
how good the context actually is before measuring its effect on formalization.

Augments cache/formalization_eval.pkl -> cache/formalization_eval_rag.pkl with a
"retrieved" field (list of decl_names, best-first).

Run (after build_formalization_eval.py; uses query_head_full.pt if present):
    python scripts/build_rag_context.py
"""
import json
import pickle
import statistics as st
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.formal_retriever import FormalRetriever

CACHE = Path(__file__).resolve().parent.parent / "cache"
K = 15


def load_head_weight(D):
    for fn in ("query_head_full.pt", "query_head_split.pt"):
        p = CACHE / fn
        if p.exists():
            sd = torch.load(p, map_location="cpu")
            for v in sd.values():
                if v.ndim == 2 and v.shape == (D, D):
                    print(f"[head] loaded {fn}")
                    return v
    print("[head] none found -> identity (raw cosine)")
    return torch.eye(D)


def main():
    r = FormalRetriever(CACHE / "formal_emb.f16.npy", CACHE / "formal_ids.json")
    row_of, ids = r.row_of, r.ids
    E = torch.from_numpy(r.emb)
    N, D = E.shape
    W = load_head_weight(D)
    names = json.loads((CACHE / "decl_names.json").read_text())
    freq = json.loads((CACHE / "premise_freq_train.json").read_text())
    ev = pickle.load(open(CACHE / "formalization_eval.pkl", "rb"))
    print(f"eval targets: {len(ev)}")

    rec = []; rec_rare = [0, 0]; rec_comm = [0, 0]
    for t, v in ev.items():
        q = (W @ E[row_of[t]]); q = q / (q.norm() + 1e-12)
        scores = E @ q
        scores[row_of[t]] = -1e9
        topk = torch.topk(scores, K).indices.tolist()
        ret_ids = [ids[i] for i in topk]
        v["retrieved"] = [names.get(i) for i in ret_ids]
        gold_ids = {p["id"] for p in v["premises"]}
        hit = gold_ids & set(ret_ids)
        rec.append(len(hit) / len(gold_ids))
        for p in v["premises"]:
            f = freq.get(p["id"], 0)
            tgt = rec_rare if f <= 3 else rec_comm if f >= 100 else None
            if tgt is not None:
                tgt[1] += 1; tgt[0] += (p["id"] in hit)

    print(f"\nretrieval recall@{K} on eval subset: {st.mean(rec):.3f}")
    print(f"  rare premises:   {rec_rare[0]}/{rec_rare[1]} = "
          f"{rec_rare[0]/max(rec_rare[1],1):.3f}")
    print(f"  common premises: {rec_comm[0]}/{rec_comm[1]} = "
          f"{rec_comm[0]/max(rec_comm[1],1):.3f}")
    print("\nsample retrieved for", ev[list(ev)[0]]["decl_name"], ":")
    print("  ", ev[list(ev)[0]]["retrieved"][:8])

    pickle.dump(ev, open(CACHE / "formalization_eval_rag.pkl", "wb"))
    print(f"\nsaved -> cache/formalization_eval_rag.pkl")


if __name__ == "__main__":
    main()
