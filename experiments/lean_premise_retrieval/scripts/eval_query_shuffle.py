"""Query-shuffle diagnostic for the learned query head.

Decomposes the learned head's gain into query-DEPENDENT (genuine retrieval)
vs query-INDEPENDENT (a memorized popularity prior baked into W).

For each test target t (gold G_t, own query q_t):
  - REAL:     rank with W·q_t      -> recall vs G_t   (genuine)
  - SHUFFLED: rank with W·q_{t+1}  -> recall vs G_t   (wrong query)

If SHUFFLED recall stays high, W emits popular premises regardless of the
query (bad). If it collapses toward cosine/0, the head is genuinely
query-conditioned. Read it BY RARITY:
  - rare premises (freq<=3): SHUFFLED should -> ~0  (a wrong query can't find a
    target's specific lemmas). High here = alarm.
  - common premises (freq>=100): SHUFFLED level ~= the popularity component.
    If ~= the frequency prior, the common-premise gain is query-independent.

Run:
    python scripts/eval_query_shuffle.py
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
KS = [10, 100]
SEED = 42
N_EVAL = 3000
EVAL_CHUNK = 400
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def main():
    rng = np.random.default_rng(SEED)
    r = FormalRetriever(CACHE / "formal_emb.f16.npy", CACHE / "formal_ids.json")
    row_of, ids = r.row_of, r.ids
    E = torch.from_numpy(r.emb).to(DEVICE)
    N, D = E.shape

    targets = pickle.load(open(CACHE / "targets_full.pkl", "rb"))
    split = json.loads((CACHE / "split.json").read_text())
    freq = json.loads((CACHE / "premise_freq_train.json").read_text())

    # robust to either a bare Linear ("weight") or a LinHead wrapper ("W.weight")
    sd = torch.load(CACHE / "query_head_full.pt", map_location="cpu")
    Wm = next(v for v in sd.values() if v.ndim == 2 and v.shape == (D, D)).to(DEVICE)

    test = []
    for t, s in split.items():
        if s != "test" or t not in row_of:
            continue
        g = [row_of[d] for d in targets[t]["gold"] if d in row_of]
        if len(g) >= 2:
            test.append((t, g))
    rng.shuffle(test)
    test = test[:N_EVAL]
    print(f"test_eval={len(test):,}  corpus={N:,}")

    def rarity(row):
        f = freq.get(ids[row], 0)
        return "rare" if f <= 3 else "common" if f >= 100 else "mid"

    # query_rows: which row's vector to use as the query for each eval target
    eval_rows = [row_of[t] for t, _ in test]

    def run(query_rows, label):
        recK = {k: [] for k in KS}
        rare = {k: [0, 0] for k in KS}
        comm = {k: [0, 0] for k in KS}
        for s in range(0, len(test), EVAL_CHUNK):
            chunk = test[s:s + EVAL_CHUNK]
            qr = torch.tensor(query_rows[s:s + EVAL_CHUNK], device=DEVICE)
            self_rows = torch.tensor(eval_rows[s:s + EVAL_CHUNK], device=DEVICE)
            Q = E[qr] @ Wm.t()
            Q = Q / (Q.norm(dim=1, keepdim=True) + 1e-12)
            S = Q @ E.t()
            for i in range(len(chunk)):
                S[i, self_rows[i]] = -1e9     # mask the EVAL target's own row
            topk = torch.topk(S, max(KS), dim=1).indices.tolist()
            for (tid, gold), ranked in zip(chunk, topk):
                gold = set(gold)
                rg = {g for g in gold if rarity(g) == "rare"}
                cg = {g for g in gold if rarity(g) == "common"}
                for k in KS:
                    rk = set(ranked[:k])
                    recK[k].append(len(gold & rk) / len(gold))
                    if rg: rare[k][0] += len(rg & rk); rare[k][1] += len(rg)
                    if cg: comm[k][0] += len(cg & rk); comm[k][1] += len(cg)
        ov = {k: st.mean(recK[k]) for k in KS}
        ra = {k: (rare[k][0]/rare[k][1] if rare[k][1] else 0) for k in KS}
        co = {k: (comm[k][0]/comm[k][1] if comm[k][1] else 0) for k in KS}
        print(f"\n[{label}]")
        print("  overall " + "  ".join(f"R@{k}={ov[k]:.3f}" for k in KS))
        print("  rare    " + "  ".join(f"R@{k}={ra[k]:.3f}" for k in KS))
        print("  common  " + "  ".join(f"R@{k}={co[k]:.3f}" for k in KS))
        return ov, ra, co

    real = run(eval_rows, "REAL (own query)")
    shuffled_rows = eval_rows[1:] + eval_rows[:1]   # derangement: t uses t+1's query
    shuf = run(shuffled_rows, "SHUFFLED (neighbor's query)")

    print("\n=== decomposition (R@100) ===")
    print(f"  overall: real {real[0][100]:.3f}  shuffled {shuf[0][100]:.3f}  "
          f"=> query-dependent lift {real[0][100]-shuf[0][100]:+.3f}")
    print(f"  rare:    real {real[1][100]:.3f}  shuffled {shuf[1][100]:.3f}  "
          f"(shuffled should be ~0 if genuinely query-conditioned)")
    print(f"  common:  real {real[2][100]:.3f}  shuffled {shuf[2][100]:.3f}  "
          f"(shuffled ~= the query-independent popularity component)")
    print("  prior R@100 (ref) = 0.384")


if __name__ == "__main__":
    main()
