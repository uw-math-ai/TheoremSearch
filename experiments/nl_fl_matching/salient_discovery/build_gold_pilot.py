"""Build a small gold-anchored pilot to choose the grader prompt by ground truth.

Uses experiments/nl_fl_matching/_gold_cache.json (1,595 blueprint gold pairs, both
sides carry a qwen3-235b slogan). Emits:
  - positives: real gold pairs            -> truth = EDGE   (formalizations)
  - hard negatives: gold formal x a DIFFERENT informal from the SAME blueprint paper
    (topically close, different theorem) -> truth = NOT EDGE
Writes blind per-pair files for two arms so subagents can't see the truth:
  /tmp/pilot_A/<id>.json  = {formal_slogan, informal_slogan}            (slogan-only)
  /tmp/pilot_B/<id>.json  = {formal_decl, formal_slogan, informal_slogan} (slogan + name)
  /tmp/pilot_truth.json   = {id: {kind, truth_edge, paper, formal_decl}}
"""
from __future__ import annotations
import json, os, random
from pathlib import Path

CACHE = Path(__file__).resolve().parents[1] / "_gold_cache.json"
N_POS = 50
N_NEG = 50
SEED = 0


def main() -> None:
    d = json.load(open(CACHE))
    F = {f["statement_id"]: f for f in d["formals"]}
    I = {i["statement_id"]: i for i in d["informals"]}
    pairs = [(i, f) for i, f in d["pairs"] if i in I and f in F]
    # restrict to pairs where BOTH slogans are non-empty
    pairs = [(i, f) for i, f in pairs if (I[i].get("slogan") or "").strip() and (F[f].get("slogan") or "").strip()]
    print(f"usable gold pairs (both slogans): {len(pairs)}")

    # gold partner sets per formal, and informals grouped by blueprint paper
    formal_partners = {}
    for i, f in pairs:
        formal_partners.setdefault(f, set()).add(i)
    by_paper = {}
    for i in I.values():
        if (i.get("slogan") or "").strip():
            by_paper.setdefault(i["paper_id"], []).append(i["statement_id"])

    rng = random.Random(SEED)
    pos = rng.sample(pairs, N_POS)

    # hard negatives: for a sampled formal, pick a same-paper informal that is NOT its gold partner
    negs = []
    used_f = [f for _, f in pos]
    rng.shuffle(used_f)
    for f in used_f:
        if len(negs) >= N_NEG:
            break
        partners = formal_partners.get(f, set())
        # paper of one of its gold informals
        p_paper = I[next(iter(partners))]["paper_id"]
        cands = [s for s in by_paper.get(p_paper, []) if s not in partners]
        if cands:
            negs.append((rng.choice(cands), f, "hard_samepaper"))
        else:
            # fallback: random informal not a partner
            allinf = [s for s in I if s not in partners and (I[s].get("slogan") or "").strip()]
            negs.append((rng.choice(allinf), f, "rand"))
    # top up negatives if needed (reuse other formals)
    while len(negs) < N_NEG:
        i, f = rng.choice(pairs)
        allinf = [s for s in I if s not in formal_partners.get(f, set()) and (I[s].get("slogan") or "").strip()]
        negs.append((rng.choice(allinf), f, "rand"))

    items = []
    for i, f in pos:
        items.append({"kind": "pos", "truth_edge": True, "neg_type": None,
                      "fsid": f, "isid": i})
    for i, f, nt in negs:
        items.append({"kind": "neg", "truth_edge": False, "neg_type": nt,
                      "fsid": f, "isid": i})
    rng.shuffle(items)

    os.makedirs("/tmp/pilot_A", exist_ok=True)
    os.makedirs("/tmp/pilot_B", exist_ok=True)
    truth = {}
    for pid, it in enumerate(items):
        f, i = F[it["fsid"]], I[it["isid"]]
        json.dump({"formal_slogan": f["slogan"], "informal_slogan": i["slogan"]},
                  open(f"/tmp/pilot_A/{pid}.json", "w"))
        json.dump({"formal_decl": f["name"], "formal_slogan": f["slogan"], "informal_slogan": i["slogan"]},
                  open(f"/tmp/pilot_B/{pid}.json", "w"))
        truth[pid] = {"kind": it["kind"], "truth_edge": it["truth_edge"], "neg_type": it["neg_type"],
                      "formal_decl": f["name"], "paper": i["paper_id"],
                      "formal_slogan": f["slogan"], "informal_slogan": i["slogan"]}
    json.dump(truth, open("/tmp/pilot_truth.json", "w"))
    from collections import Counter
    print(f"wrote {len(items)} pilot pairs (pos={N_POS}, neg={N_NEG}) -> /tmp/pilot_A, /tmp/pilot_B")
    print("neg types:", dict(Counter(it["neg_type"] for it in items if it["kind"] == "neg")))
    # leak check
    import subprocess
    leak = subprocess.run("grep -l truth /tmp/pilot_A/*.json /tmp/pilot_B/*.json 2>/dev/null | wc -l",
                          shell=True, capture_output=True, text=True).stdout.strip()
    print(f"blind files leaking 'truth': {leak} (must be 0)")


if __name__ == "__main__":
    main()
