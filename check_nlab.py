import json
from collections import Counter

data = json.load(open('data/nlab/nlab.json', encoding='utf-8'))
theorems = data['theorems']

# Proof rate by type
types = Counter(t['type'] for t in theorems)
proofs = Counter(t['type'] for t in theorems if 'proof' in t)

print('Type breakdown with proof rates:')
for t in ['theorem','lemma','proposition','corollary','definition','remark','example','note']:
    total = types[t]
    with_proof = proofs[t]
    pct = 100*with_proof/total if total else 0
    print(f'  {t:<15} {with_proof:>5}/{total:<5} ({pct:.0f}%)')

# Check if proofs are suspiciously short
proof_lengths = [len(t['proof']) for t in theorems if 'proof' in t]
print(f'\nAvg proof length: {sum(proof_lengths)/len(proof_lengths):.0f} chars')
print(f'Proofs under 50 chars:  {sum(1 for l in proof_lengths if l < 50)}')
print(f'Proofs under 20 chars:  {sum(1 for l in proof_lengths if l < 20)}')

# Sample a few proofs
print('\nSample proofs:')
for t in [x for x in theorems if 'proof' in x][:5]:
    print(f'  [{t["type"]}] {repr(t["proof"][:120])}')