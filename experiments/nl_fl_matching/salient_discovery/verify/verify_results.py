import csv, json
csv.field_size_limit(10_000_000)
B='/gscratch/amath/simku22/'
def empty(v): return not (v or '').strip()
ok=[True]
def check(label, cond):
    ok[0]=ok[0] and cond
    print(f'  [{"PASS" if cond else "FAIL"}] {label}')

print('='*68)
print('PART 1 - THE RERUN (consensus_bodied.jsonl)')
print('='*68)
new=[json.loads(l) for l in open(B+'consensus_bodied.jsonl') if l.strip()]
keys=[c['key'] for c in new]
print(f'rows: {len(new)}')
check('no duplicate keys', len(keys)==len(set(keys)))
check('edge in {True,False,None} for all', all(c['edge'] in (True,False,None) for c in new))
check('2-3 rater labels each', all(2<=len(c.get("labels",[]))<=3 for c in new))
old={c['key']:c for c in (json.loads(l) for l in open(B+'consensus_ge90_v2_all.jsonl') if l.strip())}
orig_empty=set(); ncontent=0
for r in csv.DictReader(open(B+'salient_matches_full.csv')):
    ncontent+=1
    if empty(r.get('formal_body','')): orig_empty.add(f"{r['query_sid']}|{r['cand_sid']}")
print(f'original-run rows: {len(old)}   original content rows: {ncontent}   orig-empty-body: {len(orig_empty)}')
shared=[c for c in new if c['key'] in old]
check('all rerun keys present in original run', len(shared)==len(new))
N=len(shared)
oM=sum(1 for c in shared if old[c["key"]]["edge"] is True)
nM=sum(1 for c in shared if c["edge"] is True)
flips=sum(1 for c in shared if old[c["key"]]["edge"]!=c["edge"])
t2f=sum(1 for c in shared if old[c["key"]]["edge"] is True and c["edge"] is False)
f2t=sum(1 for c in shared if old[c["key"]]["edge"] is False and c["edge"] is True)
oth=flips-t2f-f2t
sims=sorted(float(c["sim"]) for c in shared)
print(f'\nshared N={N}  sim {sims[0]:.4f}..{sims[-1]:.4f} = top {100*N/8022:.1f}% of 8,022')
print(f'original match {oM} ({100*oM/N:.1f}%)  ->  corrected match {nM} ({100*nM/N:.1f}%)   delta {nM-oM:+d} ({100*(nM-oM)/N:+.1f}pp)')
print(f'flips {flips} ({100*flips/N:.1f}%) = match->no {t2f} + no->match {f2t} + ambig {oth}')
check('flip components sum to flips', t2f+f2t+oth==flips)
had=[c for c in shared if c['key'] not in orig_empty]
emp=[c for c in shared if c['key'] in orig_empty]
check('had+empty == shared', len(had)+len(emp)==N)
def blk(name,grp):
    n=len(grp); om=sum(1 for c in grp if old[c['key']]['edge'] is True); nm=sum(1 for c in grp if c['edge'] is True)
    f=sum(1 for c in grp if old[c['key']]['edge']!=c['edge'])
    d=sum(1 for c in grp if old[c['key']]['edge'] is True and c['edge'] is False)
    u=sum(1 for c in grp if old[c['key']]['edge'] is False and c['edge'] is True)
    print(f'  {name:28} n={n:5} flips={100*f/n:4.1f}% ({d}dn/{u}up) match {100*om/n:.1f}%->{100*nm/n:.1f}%')
print('\nbody-effect (split by ORIGINAL body presence):')
blk('had body (control/noise)',had)
blk('empty body (slogan->source)',emp)

print('\n'+'='*68)
print('PART 2 - THE SAMPLING (tier_sample150_judged.jsonl)')
print('='*68)
content={f"{r['query_sid']}|{r['cand_sid']}":r for r in csv.DictReader(open(B+'tier_sample150.csv'))}
locked=json.load(open(B+'tier_sample150_keys.json'))
J=[json.loads(l) for l in open(B+'tier_sample150_judged.jsonl') if l.strip()]
jkeys=[c['key'] for c in J]
print(f'judged rows: {len(J)}')
check('no duplicate judged keys', len(jkeys)==len(set(jkeys)))
check('every judged key is in the locked sample', all(any(c['key'] in locked[t] for t in locked) for c in J))
# cross-tier contamination: judged band must equal the band the key was locked under
def locked_band(k):
    for t in locked:
        if k in locked[t]: return t
    return None
check('judged band == locked band (no cross-tier leak)', all(c['band']==locked_band(c['key']) for c in J))
print(f'\n{"tier":12}{"judged":>7}{"body+":>7}{"match":>7}{"rate":>7}   slogan-only')
for band in ('0.80-0.90','0.70-0.80','0.60-0.70'):
    sub=[c for c in J if c['band']==band]
    bp=[c for c in sub if not empty(content[c['key']].get('formal_body',''))]
    m=sum(1 for c in bp if c['edge'] is True)
    so=len(sub)-len(bp)
    print(f'{band:12}{len(sub):>7}{len(bp):>7}{m:>7}{100*m/len(bp):>6.0f}%   {so}')
print(f'\nALL CHECKS PASSED: {ok[0]}')
