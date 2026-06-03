import csv, json, glob
from collections import Counter
csv.field_size_limit(10_000_000)
B='/gscratch/amath/simku22/'
def empty(v): return not (v or '').strip()
ok=[True]
def chk(l,c):
    ok[0]=ok[0] and c; print(f'  [{"PASS" if c else "FAIL"}] {l}')

print('='*64)
print('PRE-FLIGHT: the >=0.90 random sample (BEFORE judging)')
print('='*64)
content={f"{r['query_sid']}|{r['cand_sid']}":r for r in csv.DictReader(open(B+'tier_sample150.csv'))}
locked=json.load(open(B+'tier_sample150_keys.json'))
samp=[r for r in csv.DictReader(open(B+'tier_sample150.csv')) if r['band']=='0.90-1.0']
print(f'rows in 0.90-1.0 sample: {len(samp)}')
chk('exactly 150 rows', len(samp)==150)
sims=[float(r['sim']) for r in samp]
chk('all sim in [0.90,1.0)', all(0.90<=s<1.0001 for s in sims))
chk('no duplicate keys', len({f"{r['query_sid']}|{r['cand_sid']}" for r in samp})==150)
chk('keys == locked seed-0 draw', sorted(f"{r['query_sid']}|{r['cand_sid']}" for r in samp)==sorted(locked['0.90-1.0']))
chk('formal_slogan present (all)', all(not empty(r['formal_slogan']) for r in samp))
chk('informal_slogan present (all)', all(not empty(r['informal_slogan']) for r in samp))
chk('informal_body present (all)', all(not empty(r['informal_body']) for r in samp))
bp=sum(1 for r in samp if not empty(r['formal_body']))
print(f'  formal signature present: {bp}/150 ({100*bp/150:.0f}%)  -> {150-bp} slogan-only')

# representativeness vs FULL 0.90-1.0 population (recompute from shards)
CORE={'Init','Batteries','Std','Lean'}
def proj(m): return (m or '').split('.')[0]
def cls3(m):
    p=proj(m); return 'Mathlib' if p=='Mathlib' else ('CoreLean' if p in CORE else 'Project')
pop=[]
for f in glob.glob(B+'salient_sweep/*.jsonl')+glob.glob(B+'salient_sweep_bottom/*.jsonl'):
    for line in open(f):
        line=line.strip()
        if not line: continue
        try: r=json.loads(line)
        except: continue
        if not r['n']: continue
        s=r['results'][0]['sim']
        if 0.90<=s<1.0001: pop.append((s, r['decl_name']))
# need module for pop cls -> use corrected DB modmap
import sqlite3
db=B+'corpus_v3_fixed/corpus_v3 (corrected ingestion order).db'
c=sqlite3.connect(f'file:{db}?mode=ro&immutable=1',uri=True)
modmap={n:m for n,m in c.execute('SELECT full_name,module FROM nodes')}; c.close()
pmean=sum(s for s,_ in pop)/len(pop)
pcomp=Counter(cls3(modmap.get(d,'')) for _,d in pop)
smean=sum(sims)/150
scomp=Counter(cls3(r['formal_module']) for r in samp)
print(f'\n  REPRESENTATIVENESS  population(n={len(pop):,})  vs  sample(150):')
print(f'    mean sim     {pmean:.3f}        {smean:.3f}')
for k in ('Mathlib','CoreLean','Project'):
    print(f'    {k:9}    {100*pcomp[k]/len(pop):5.1f}%       {100*scomp[k]/150:5.1f}%')

print('\n'+'='*64)
print('RE-VERIFY: the 3 already-judged bins')
print('='*64)
J=[json.loads(l) for l in open(B+'tier_sample150_judged.jsonl') if l.strip()]
jk=[c['key'] for c in J]
chk('no duplicate judged keys', len(jk)==len(set(jk)))
def lband(k):
    for t in locked:
        if k in locked[t]: return t
chk('every judged key in locked sample', all(any(c['key'] in locked[t] for t in locked) for c in J))
chk('judged band == locked band (no cross-tier leak)', all(c['band']==lband(c['key']) for c in J))
print(f'  judged so far: {len(J)} (expect 450 = 3 tiers x 150)')
for band in ('0.80-0.90','0.70-0.80','0.60-0.70'):
    sub=[c for c in J if c['band']==band]
    bpr=[c for c in sub if not empty(content[c['key']].get('formal_body',''))]
    m=sum(1 for c in bpr if c['edge'] is True)
    print(f'    {band}: n={len(sub)}  body+={len(bpr)}  match={m} ({100*m/len(bpr):.0f}%)  slogan-only={len(sub)-len(bpr)}')
print(f'\nALL PRE-FLIGHT CHECKS PASSED: {ok[0]}')
