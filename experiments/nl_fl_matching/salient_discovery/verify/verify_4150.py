import json
from collections import Counter
B='/gscratch/amath/simku22/'
new=[json.loads(l) for l in open(B+'consensus_bodied.jsonl') if l.strip()]
N=len(new)
print(f"total re-judged edges: {N}")
print(f"unique keys: {len({c['key'] for c in new})}  (dupes: {N-len({c['key'] for c in new})})")

# edge True/False/None
edge=Counter(c['edge'] for c in new)
print(f"\nedge verdict: match(True)={edge[True]}  non-match(False)={edge[False]}  ambiguous(None)={edge[None]}")
print(f"  reconcile: {edge[True]}+{edge[False]}+{edge[None]} = {edge[True]+edge[False]+edge[None]}  (==N? {edge[True]+edge[False]+edge[None]==N})")

# fine label among ALL, and among matches
fin=Counter(c['final'] for c in new)
print(f"\nfine label 'final' over all {N}: {dict(fin)}")

# matches = edge True; break by final
matches=[c for c in new if c['edge'] is True]
fm=Counter(c['final'] for c in matches)
nm=len(matches)
print(f"\nMATCHES (edge=True): {nm}")
for k in ('exact','inexact','(split)',None):
    if fm.get(k): print(f"  {k}: {fm[k]} ({100*fm[k]/nm:.1f}% of matches)")
# status of the edge-ambiguous (counted as match but no exact/inexact)
print(f"\nstatus breakdown: {dict(Counter(c['status'] for c in new))}")
ea=[c for c in matches if c['status']=='edge_ambiguous']
print(f"edge_ambiguous matches (agreed edge, split on strength): {len(ea)}  final values: {Counter(c['final'] for c in ea)}")

# reconcile: exact + inexact + edge_ambiguous == total matches?
ex=fm.get('exact',0); ix=fm.get('inexact',0); other=nm-ex-ix
print(f"\nRECONCILE matches: exact {ex} + inexact {ix} + other {other} = {ex+ix+other} (==matches {nm}? {ex+ix+other==nm})")
print(f"  'other' = {other} edge-ambiguous (agreed it's an edge, raters split exact-vs-inexact)")
print(f"\nHEADLINE: of {N} edges -> {nm} matches ({100*nm/N:.1f}%): {ex} exact + {ix} inexact + {other} edge-ambiguous; {edge[False]} non-match")
