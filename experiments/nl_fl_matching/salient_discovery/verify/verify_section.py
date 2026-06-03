import csv, json
csv.field_size_limit(10_000_000)
B='/gscratch/amath/simku22/'
def empty(v): return not (v or '').strip()
orig={f"{r['query_sid']}|{r['cand_sid']}":r for r in csv.DictReader(open(B+'salient_matches_full.csv'))}

# B) candidate-pair product
arxiv=11_749_537; lean=388_105
print(f"B) 11,749,537 x 388,105 = {arxiv*lean:,} = {arxiv*lean/1e12:.2f} trillion   (paper says 4.54)")
print(f"   11,700,000 x 388,105 = {11_700_000*lean/1e12:.2f} trillion")

# C) filter pct
print(f"C) 2,448 / 388,105 = {100*2448/388105:.3f}%   (paper says ~0.65%)")

# D) blueprint edges: in the 8,022 vs in the 4,150 re-judged
old=[json.loads(l) for l in open(B+'consensus_ge90_v2_all.jsonl') if l.strip()]
new=[json.loads(l) for l in open(B+'consensus_bodied.jsonl') if l.strip()]
def is_bp(k):
    s=(orig.get(k,{}).get('informal_source','') or '').lower()
    return s and 'arx' not in s
bp8=sum(1 for c in old if is_bp(c['key']))
bp4=sum(1 for c in new if is_bp(c['key']))
print(f"D) blueprint edges in 8,022 = {bp8}   |   in the 4,150 re-judged = {bp4}   (paper says 284 in the 4,150)")

# E) corrected 4,150 breakdown for a Result paragraph
newkey={c['key']:c for c in new}
N=len(new)
matches=[c for c in new if c['edge'] is True]
fin={}
for c in matches: fin[c['final']]=fin.get(c['final'],0)+1
st={}
for c in new: st[c['status']]=st.get(c['status'],0)+1
nm=len(matches)
print(f"\nE) CORRECTED 4,150 tier (for the Result paragraph):")
print(f"   matches {nm} ({100*nm/N:.1f}%)  non-match {N-nm-sum(1 for c in new if c['edge'] is None)} ")
print(f"   of matches: exact {fin.get('exact',0)} ({100*fin.get('exact',0)/nm:.1f}%)  inexact {fin.get('inexact',0)} ({100*fin.get('inexact',0)/nm:.1f}%)  split {fin.get('(split)',0)} ({100*fin.get('(split)',0)/nm:.1f}%)")
print(f"   consensus: confirmed {st.get('confirmed',0)} ({100*st.get('confirmed',0)/N:.1f}%)  tiebroken {st.get('tiebroken',0)} ({100*st.get('tiebroken',0)/N:.1f}%)  edge-amb {st.get('edge_ambiguous',0)} ({100*st.get('edge_ambiguous',0)/N:.1f}%)")
unj=sum(1 for c in new if c['final']=='unjudgeable')
print(f"   unjudgeable: {unj}")

# A) blueprint pair count — count gold pairs in _gold_cache if present
import os
for p in ['_gold_cache.json','TheoremSearch/experiments/nl_fl_matching/salient_discovery/data/_gold_cache.json']:
    fp=B+p
    if os.path.exists(fp):
        d=json.load(open(fp))
        print(f"\nA) {p}: {len(d) if isinstance(d,(list,dict)) else '?'} entries")
        break
else:
    print("\nA) _gold_cache.json not found at expected paths")
