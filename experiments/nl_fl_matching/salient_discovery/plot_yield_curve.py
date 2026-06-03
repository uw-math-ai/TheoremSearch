"""Yield-curve bar chart: judged match rate per similarity bin.

For a reader who knew the OLD method (trust a 0.85 cutoff, count everything above
as a match). Bars = actual judged match rate per bin from the 150/bin random
samples; a dashed line marks the old 0.85 cutoff so the gap (what the cutoff
falsely counted) is obvious.
"""
import json
from collections import defaultdict
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = __file__.rsplit("/", 1)[0]
ORDER = ["0.90-1.0", "0.80-0.90", "0.70-0.80", "0.60-0.70"]
LABEL = {"0.90-1.0": "≥0.90", "0.80-0.90": "0.80–0.90",
         "0.70-0.80": "0.70–0.80", "0.60-0.70": "0.60–0.70"}

bins = defaultdict(lambda: [0, 0])  # band -> [match, total]
for l in open(f"{HERE}/data/tier_sample150_judged.jsonl"):
    l = l.strip()
    if not l:
        continue
    c = json.loads(l)
    b = c["band"]
    if b not in ORDER:
        continue
    bins[b][1] += 1
    if c["edge"] is True:
        bins[b][0] += 1

rates = [100 * bins[b][0] / bins[b][1] for b in ORDER]
ns = [bins[b][1] for b in ORDER]
labels = [LABEL[b] for b in ORDER]
colors = ["#2a7", "#7a3", "#d83", "#c33"]  # green->red, high->low match

fig, ax = plt.subplots(figsize=(6.4, 4.2))
bars = ax.bar(labels, rates, color=colors, width=0.7, zorder=3)
for bar, r, n, b in zip(bars, rates, ns, ORDER):
    ax.text(bar.get_x() + bar.get_width() / 2, r + 2, f"{r:.0f}%",
            ha="center", va="bottom", fontsize=11, fontweight="bold")
    ax.text(bar.get_x() + bar.get_width() / 2, 3, f"n={n}\n{bins[b][0]} match",
            ha="center", va="bottom", fontsize=8, color="white")

# the old 0.85-cutoff region: it counted EVERYTHING >=0.85 as a match (~bins 1+2)
ax.axvspan(-0.5, 1.5, color="gray", alpha=0.12, zorder=0)
ax.set_ylim(0, 108)
ax.text(0.5, 103, "old method: counted all ≥0.85 as matches (no judging)",
        ha="center", va="center", fontsize=8.5, color="dimgray", style="italic")

ax.set_ylabel("judged match rate (%)")
ax.set_xlabel("cosine similarity bin")
ax.set_yticks([0, 20, 40, 60, 80, 100])
ax.set_title("Match rate collapses below 0.90\n(150 random candidates/bin, judged with Lean signature)")
ax.grid(True, axis="y", alpha=0.3, zorder=0)
fig.tight_layout()
fig.savefig(f"{HERE}/data/yield_curve_bars.png", dpi=150)
print(f"wrote data/yield_curve_bars.png")
for b, r, n in zip(ORDER, rates, ns):
    print(f"  {b}: {r:.0f}% match (n={n})")


# ---- PIE: verdict composition of the judged >=0.90 tier (the "yield") ----
from collections import Counter
fin = Counter()
N = 0
for l in open(f"{HERE}/data/consensus_bodied.jsonl"):
    l = l.strip()
    if not l:
        continue
    c = json.loads(l)
    N += 1
    if c["edge"] is True and c.get("final") in ("exact", "inexact"):
        fin[c["final"]] += 1
    elif c["edge"] is True:
        fin["edge-ambiguous"] += 1
    else:
        fin["wrong"] += 1

parts = [("exact", "#2a7"), ("inexact", "#d83"), ("edge-ambiguous", "#999"), ("wrong", "#c33")]
vals = [fin[k] for k, _ in parts]
cols = [c for _, c in parts]
labs = [f"{k}\n{fin[k]:,} ({100*fin[k]/N:.0f}%)" for k, _ in parts]

fig2, ax2 = plt.subplots(figsize=(5.2, 5.2))
ax2.pie(vals, labels=labs, colors=cols, startangle=90, counterclock=False,
        wedgeprops=dict(width=0.45, edgecolor="white", linewidth=1.5),
        textprops=dict(fontsize=9))
match = fin["exact"] + fin["inexact"] + fin["edge-ambiguous"]
ax2.text(0, 0, f"{100*match/N:.0f}%\nmatch", ha="center", va="center",
         fontsize=15, fontweight="bold")
ax2.set_title(f"Verdict composition, judged ≥0.90 tier\n(n={N:,}, corrected run)")
fig2.tight_layout()
fig2.savefig(f"{HERE}/data/yield_pie.png", dpi=150)
print(f"wrote data/yield_pie.png  (match {100*match/N:.0f}%: " +
      ", ".join(f"{k} {fin[k]}" for k, _ in parts) + ")")
