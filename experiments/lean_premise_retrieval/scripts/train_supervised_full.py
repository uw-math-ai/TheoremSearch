"""S1 (supervised ceiling) + S2 (scaling curve) in one run.

Trains the linear query head at increasing train-set sizes and records test
recall@k for each -> the scaling curve. The largest size is the supervised
ceiling. Adds POPULAR-PREMISE hard negatives (the frequency-prior set) so the
head can't cheaply win by emitting popular lemmas — it must place them only
when query-relevant.

If recall keeps rising with train size, that is direct evidence that
lean-graph's *scale* is the enabling resource.

Saves the largest-size head to cache/query_head_full.pt for the RAG experiment.

Run:
    python scripts/train_supervised_full.py
"""
import json
import pickle
import statistics as st
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.formal_retriever import FormalRetriever

CACHE = Path(__file__).resolve().parent.parent / "cache"
KS = [5, 10, 20, 50, 100]
SEED = 42
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
SIZES = [10000, 60000, 300000]
N_EVAL = 3000
EPOCHS, BS, N_RAND_NEG, N_POP_NEG, TEMP = 6, 256, 1536, 512, 0.05
EVAL_CHUNK = 400


def bucket(n):
    return "2" if n == 2 else "3" if n == 3 else "4-5" if n <= 5 else "6+"


def main():
    torch.manual_seed(SEED); rng = np.random.default_rng(SEED)
    print(f"[load] (device={DEVICE})")
    r = FormalRetriever(CACHE / "formal_emb.f16.npy", CACHE / "formal_ids.json")
    row_of, ids = r.row_of, r.ids
    E = torch.from_numpy(r.emb).to(DEVICE)
    N, D = E.shape
    targets = pickle.load(open(CACHE / "targets_full.pkl", "rb"))
    split = json.loads((CACHE / "split.json").read_text())
    freq = json.loads((CACHE / "premise_freq_train.json").read_text())

    def prep(s):
        out = []
        for t, ss in split.items():
            if ss != s or t not in row_of:
                continue
            g = [row_of[d] for d in targets[t]["gold"] if d in row_of]
            if len(g) >= 2:
                out.append((row_of[t], g))
        return out

    train_all = prep("train"); test = prep("test")
    rng.shuffle(train_all); rng.shuffle(test); test = test[:N_EVAL]
    print(f"[data] train_all={len(train_all):,}  test={len(test):,}")

    # popular-premise rows for hard negatives
    from collections import Counter
    pop_rows = [row_of[p] for p, _ in Counter(freq).most_common(5000) if p in row_of]
    pop_rows = np.array(pop_rows)

    def rarity(row):
        f = freq.get(ids[row], 0)
        return "rare" if f <= 3 else "common" if f >= 100 else "mid"

    def evaluate(head):
        recK = {k: [] for k in KS}; rare = {k: [0, 0] for k in KS}; comm = {k: [0, 0] for k in KS}
        for s in range(0, len(test), EVAL_CHUNK):
            chunk = test[s:s + EVAL_CHUNK]
            qr = torch.tensor([tr for tr, _ in chunk], device=DEVICE)
            Q = head(E[qr]); Q = Q / (Q.norm(dim=1, keepdim=True) + 1e-12)
            S = Q @ E.t()
            for i in range(len(chunk)):
                S[i, qr[i]] = -1e9
            topk = torch.topk(S, max(KS), dim=1).indices.tolist()
            for (tr, gold), ranked in zip(chunk, topk):
                gold = set(gold)
                rg = {g for g in gold if rarity(g) == "rare"}; cg = {g for g in gold if rarity(g) == "common"}
                for k in KS:
                    rk = set(ranked[:k]); recK[k].append(len(gold & rk) / len(gold))
                    if rg: rare[k][0] += len(rg & rk); rare[k][1] += len(rg)
                    if cg: comm[k][0] += len(cg & rk); comm[k][1] += len(cg)
        ov = {k: st.mean(recK[k]) for k in KS}
        ra = {k: (rare[k][0]/rare[k][1] if rare[k][1] else 0) for k in KS}
        co = {k: (comm[k][0]/comm[k][1] if comm[k][1] else 0) for k in KS}
        return ov, ra, co

    class LinHead(nn.Module):
        def __init__(s):
            super().__init__(); s.W = nn.Linear(D, D, bias=False)
            with torch.no_grad(): s.W.weight.copy_(torch.eye(D))
        def forward(s, x): return s.W(x)

    curve = {}
    final_head = None
    for nt in SIZES:
        if nt > len(train_all):
            continue
        train = train_all[:nt]
        head = LinHead().to(DEVICE)
        opt = torch.optim.AdamW(head.parameters(), lr=1e-4, weight_decay=1e-3)
        t0 = time.time()
        print(f"\n[size {nt:,}] training {EPOCHS} ep...")
        for ep in range(EPOCHS):
            rng.shuffle(train); losses = []
            for s in range(0, len(train), BS):
                batch = train[s:s + BS]
                q = E[torch.tensor([tr for tr, _ in batch], device=DEVICE)]
                qp = head(q); qp = qp / (qp.norm(dim=1, keepdim=True) + 1e-12)
                pos = [g[rng.integers(len(g))] for _, g in batch]
                neg = rng.choice(N, size=N_RAND_NEG, replace=False).tolist()
                hard = rng.choice(pop_rows, size=N_POP_NEG, replace=False).tolist()
                C = E[torch.tensor(pos + neg + hard, device=DEVICE)]
                logits = qp @ C.t() / TEMP
                loss = nn.functional.cross_entropy(logits, torch.arange(len(batch), device=DEVICE))
                opt.zero_grad(); loss.backward(); opt.step(); losses.append(loss.item())
            print(f"  ep {ep} loss={st.mean(losses):.3f}  ({time.time()-t0:.0f}s)")
        ov, ra, co = evaluate(head)
        curve[nt] = {"overall": ov, "rare": ra, "common": co}
        print(f"[size {nt:,}] R@100={ov[100]:.3f} (rare {ra[100]:.3f}, common {co[100]:.3f})")
        final_head = head

    print("\n=== SCALING CURVE (test R@100) ===")
    for nt in sorted(curve):
        c = curve[nt]
        print(f"  n_train={nt:>7,}  R@10={c['overall'][10]:.3f}  R@100={c['overall'][100]:.3f}  "
              f"rare@100={c['rare'][100]:.3f}  common@100={c['common'][100]:.3f}")
    torch.save(final_head.state_dict(), CACHE / "query_head_full.pt")
    (CACHE / "scaling_curve.json").write_text(json.dumps(
        {str(k): v for k, v in curve.items()}))
    print(f"\nsaved head -> cache/query_head_full.pt, curve -> cache/scaling_curve.json")


if __name__ == "__main__":
    main()
