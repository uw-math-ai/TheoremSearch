import csv, json
csv.field_size_limit(10_000_000)
B='/gscratch/amath/simku22/'
def empty(v): return not (v or '').strip()
orig={f"{r['query_sid']}|{r['cand_sid']}":r for r in csv.DictReader(open(B+'salient_matches_full.csv'))}
bodied={f"{r['query_sid']}|{r['cand_sid']}":r for r in csv.DictReader(open(B+'salient_matches_full_bodied.csv'))}
old={c['key']:c for c in (json.loads(l) for l in open(B+'consensus_ge90_v2_all.jsonl') if l.strip())}
new=[json.loads(l) for l in open(B+'consensus_bodied.jsonl') if l.strip()]

print("CLAIM-BY-CLAIM (paragraph numbers):")
# 1. 8,022 edges all >=0.90
print(f"1) '8,022 edges'                    -> {len(old)}  {'OK' if len(old)==8022 else 'MISMATCH'}")

# 2. ref 94% -- on the 8,022 specifically, arXiv rows
o8=[old[k] for k in old]
arx=[k for k in old if 'arx' in (orig.get(k,{}).get('informal_source','') or '').lower()]
refp=sum(1 for k in arx if not empty(orig.get(k,{}).get('informal_ref','')))
print(f"2) 'ref (94%)' on 8,022 arXiv rows  -> {refp}/{len(arx)} = {100*refp/len(arx):.1f}%   (n_arXiv={len(arx)} of 8,022)")

# 3. signature 99.7% on the 4,150 re-judged
nb=sum(1 for c in new if not empty(bodied.get(c['key'],{}).get('formal_body','')))
print(f"3) 'signature (99.7%)' on 4,150     -> {nb}/{len(new)} = {100*nb/len(new):.1f}%")
# and for context, signature coverage on the full 8,022 (original pilot)
ob=sum(1 for k in old if not empty(orig.get(k,{}).get('formal_body','')))
print(f"   [context] signature on 8,022 pilot -> {ob}/{len(old)} = {100*ob/len(old):.1f}% present  ({len(old)-ob} = {100*(len(old)-ob)/len(old):.1f}% empty)")

# 4. 4,850 (60.5%) empty
print(f"4) '4,850 (60.5%) empty'            -> {len(old)-ob} = {100*(len(old)-ob)/len(old):.1f}%  {'OK' if len(old)-ob==4850 else 'MISMATCH'}")

# 5/6. 4,150 re-judged, sim>=0.917 top-down
sims=sorted(float(c['sim']) for c in new)
print(f"5) '4,150 re-judged'                -> {len(new)}  sim {sims[0]:.4f}..{sims[-1]:.4f}  (top {100*len(new)/8022:.1f}%)")

# classify by ORIGINAL signature presence
shared=[c for c in new if c['key'] in old]
emp=[c for c in shared if empty(orig.get(c['key'],{}).get('formal_body',''))]
had=[c for c in shared if not empty(orig.get(c['key'],{}).get('formal_body',''))]
def flips(grp):
    f=sum(1 for c in grp if old[c['key']]['edge']!=c['edge'])
    d=sum(1 for c in grp if old[c['key']]['edge'] is True and c['edge'] is False)
    u=sum(1 for c in grp if old[c['key']]['edge'] is False and c['edge'] is True)
    om=sum(1 for c in grp if old[c['key']]['edge'] is True); nm=sum(1 for c in grp if c['edge'] is True)
    return len(grp),f,d,u,om,nm
ne,ef,ed,eu,eom,enm=flips(emp)
hn,hf,hd,hu,hom,hnm=flips(had)
print(f"7) recovered-sig: '12.5% flipped'  -> {ef}/{ne} = {100*ef/ne:.1f}%")
print(f"8) 'match->non-match (XXX of 310)'  -> {ed} down of {ef} total flips  ({eu} up)   PARAGRAPH SAYS 240 -> {'OK' if ed==240 else f'MISMATCH (true={ed})'}")
print(f"9) recovered-sig match '93.4->85.8'-> {100*eom/ne:.1f}% -> {100*enm/ne:.1f}%")
print(f"10) control 'only 2.9%'            -> {hf}/{hn} = {100*hf/hn:.1f}%  ({hd}dn/{hu}up)")
# 11. 1 in 11
print(f"11) '1 in 11 false matches removed':")
print(f"      net flip rate (12.5-2.9)     = {100*ef/ne-100*hf/hn:.1f}%  -> 1 in {1/((ef/ne)-(hf/hn)):.1f}")
print(f"      match-rate drop on recovered = {100*eom/ne-100*enm/ne:.1f}pp  -> as frac of old matches {100*(eom-enm)/eom:.1f}% = 1 in {eom/(eom-enm):.1f}")
print(f"      gross demotions/old-matches  = {ed}/{eom} = {100*ed/eom:.1f}% = 1 in {eom/ed:.1f}")
# 12. overall 4,150: 88.8 vs 93.1
tn,tf,td,tu,tom,tnm=flips(shared)
print(f"12) re-judged tier '88.8 vs 93.1'  -> corrected {100*tnm/tn:.1f}%  slogan-only {100*tom/tn:.1f}%")
