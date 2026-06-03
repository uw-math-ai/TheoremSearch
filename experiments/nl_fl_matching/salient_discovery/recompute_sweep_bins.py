"""Authoritative per-bin recompute of the full f->i sweep, from raw shard JSONL.

READ-ONLY over the raw sweep output (no RDS). Bins each query's rank-1 informal
match by cosine similarity (incl. empties), by class. Run on klone where the
shards live.
"""
import json, glob
from collections import Counter

DIRS = ["/gscratch/amath/simku22/salient_sweep",
        "/gscratch/amath/simku22/salient_sweep_bottom"]


def binof(s):
    if s >= 0.95: return "0.95-1.0"
    if s >= 0.90: return "0.90-0.95"
    if s >= 0.85: return "0.85-0.90"
    if s >= 0.75: return "0.75-0.85"
    return "<0.75"


bins = Counter(); bcls = Counter(); tot = Counter()
n_total = 0
for d in DIRS:
    for f in glob.glob(d + "/*.jsonl"):
        for line in open(f):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            n_total += 1
            cl = r["cls"]; tot[cl] += 1
            if r["n"] == 0:
                bins["empty"] += 1; bcls[("empty", cl)] += 1
            else:
                b = binof(r["results"][0]["sim"])
                bins[b] += 1; bcls[(b, cl)] += 1

order = ["0.95-1.0", "0.90-0.95", "0.85-0.90", "0.75-0.85", "<0.75", "empty"]
ml = tot["mathlib"]; pr = tot["project"]
print("TOTAL swept: {:,}  (mathlib {:,}, project {:,})\n".format(n_total, ml, pr))
print("{:<11}{:>9}{:>7}{:>10}{:>10}".format("bin", "total", "pct", "mathlib", "project"))
print("-" * 48)
for b in order:
    t = bins[b]; m = bcls[(b, "mathlib")]; p = bcls[(b, "project")]
    print("{:<11}{:>9,}{:>6.1f}%{:>10,}{:>10,}".format(b, t, 100 * t / n_total, m, p))
print("-" * 48)
nonempty = n_total - bins["empty"]
strong = bins["0.95-1.0"] + bins["0.90-0.95"] + bins["0.85-0.90"]
ge90 = bins["0.95-1.0"] + bins["0.90-0.95"]
print("retrieved (non-empty): {:,} = {:.1f}%   |   empty: {:,} = {:.1f}%".format(
    nonempty, 100 * nonempty / n_total, bins["empty"], 100 * bins["empty"] / n_total))
print("strong (>=0.85): {:,} = {:.1f}% of all swept".format(strong, 100 * strong / n_total))
print(">=0.90 (all classes/sources): {:,}".format(ge90))
