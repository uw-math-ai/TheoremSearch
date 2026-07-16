"""Stage 3a: characterize the minority (raw-wins) cases and test whether notation
density predicts the slogan advantage. Reads data/results.json, prints to stdout."""
import os, re, json
import numpy as np

items = json.load(open(os.path.join(os.path.dirname(__file__), "data", "results.json")))


def notation_density(s):
    math_spans = re.findall(r"\$[^$]*\$|\\\([^)]*\\\)|\\\[[^]]*\\\]", s)
    math_chars = sum(len(m) for m in math_spans)
    sym = len(re.findall(r"[=<>+\^_{}|\\]", s))
    return (math_chars + sym) / max(len(s), 1)


for it in items:
    it["notdens"] = notation_density(it["raw"])
    it["rawlen"] = len(it["raw"])

print("=" * 90)
print("WHERE RAW-LATEX WINS (asym config, slogan NOT closer)")
print("=" * 90)
losers = sorted([it for it in items if it["asym_gap"] < 0], key=lambda x: x["asym_gap"])
print(f"{len(losers)}/{len(items)} cases where raw is closer than slogan (asym).")
for it in losers:
    print(f"\n[{it['category']}] gap={it['asym_gap']:+.4f} (raw={it['asym_raw']:.3f} slo={it['asym_slo']:.3f}) notdens={it['notdens']:.2f}")
    print("   RAW  :", it["raw"][:150].replace("\n", " "))
    print("   SLGN :", it["slogan"][:150])
    print("   QUERY:", it["query"][:150])

print("\n" + "=" * 90)
print("BIGGEST SLOGAN WINS (top 5)")
print("=" * 90)
for it in sorted(items, key=lambda x: -x["asym_gap"])[:5]:
    print(f"\n[{it['category']}] gap={it['asym_gap']:+.4f} notdens={it['notdens']:.2f}")
    print("   RAW  :", it["raw"][:150].replace("\n", " "))
    print("   SLGN :", it["slogan"][:120])

print("\n" + "=" * 90)
print("NOTATION DENSITY vs GAP")
print("=" * 90)
nd = np.array([it["notdens"] for it in items])
gap = np.array([it["asym_gap"] for it in items])
rl = np.array([it["rawlen"] for it in items])
pear = lambda a, b: float(((a - a.mean()) @ (b - b.mean())) / (np.linalg.norm(a - a.mean()) * np.linalg.norm(b - b.mean())))
print(f"  corr(notation_density, gap) = {pear(nd, gap):+.3f}")
print(f"  corr(raw_length, gap)       = {pear(rl, gap):+.3f}")
order = np.argsort(nd)
for lab, sl in [("LOW notation", order[:33]), ("MID", order[33:66]), ("HIGH notation", order[66:])]:
    g, ndd = gap[sl], nd[sl]
    print(f"  {lab:14s} notdens~[{ndd.min():.2f},{ndd.max():.2f}]  mean gap={g.mean():+.4f}  slogan-wins={np.mean(g > 0):.0%}")
