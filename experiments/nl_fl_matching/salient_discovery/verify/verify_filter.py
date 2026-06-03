import csv, re, sys
sys.path.insert(0,'/gscratch/amath/simku22/TheoremSearch'); sys.path.insert(0,'/gscratch/amath/simku22/TheoremSearch/rds')
csv.field_size_limit(10_000_000)
B='/gscratch/amath/simku22/'

# ---- EXACT gate rules copied from saliency_prior.py ----
KIND_NORM={"thm":"theorem","def":"definition","inst":"instance","struct":"structure","ctor":"constructor","ind":"inductive"}
GATE_KINDS={"theorem","definition","instance","structure","class","inductive","opaque","axiom"}
_INTERNAL=re.compile(r"(^|\.)_")
_INTERNAL_FINAL=re.compile(r"\.(match_|proof_)[^.]*$")
_INTERNAL_SUFFIX=re.compile(r"\.(injEq|sizeOf_spec|noConfusion|brecOn|ndrec|toCtorIdx)(\.|$)")
def is_internal(n):
    if not n: return True
    return bool(_INTERNAL.search(n) or _INTERNAL_FINAL.search(n) or _INTERNAL_SUFFIX.search(n))

# ---- pull ALL formal nodes (Lean Repo): sid, decl_name, kind ----
from utils.connect import get_rds_connection
conn=get_rds_connection("v2"); conn.autocommit=True; cur=conn.cursor()
cur.execute("SET default_transaction_read_only=on")
cur.execute("""SELECT st.statement_id::text, fm.decl_name, st.kind
               FROM statement st JOIN formal_metadata fm ON fm.statement_id=st.statement_id
               JOIN paper p ON p.paper_id=st.paper_id WHERE p.source='Lean Repo'""")
nodes=cur.fetchall(); conn.close()
TOTAL=len(nodes)
print(f"TOTAL formal nodes (Lean Repo): {TOTAL:,}")

# ---- apply gate, break down drops by reason ----
surv=0; drop_kind=0; drop_name=0; both=0
kindctr={}
for sid,decl,kind in nodes:
    nk=KIND_NORM.get(kind,kind)
    bad_kind = nk not in GATE_KINDS
    bad_name = is_internal(decl)
    if bad_kind and bad_name: both+=1
    if bad_kind: drop_kind+=1; kindctr[nk]=kindctr.get(nk,0)+1
    if bad_name and not bad_kind: drop_name+=1
    if not bad_kind and not bad_name: surv+=1
dropped=TOTAL-surv
print(f"\n--- GATE (kind in whitelist AND not compiler-internal name) ---")
print(f"survivors (gate-pass):      {surv:,}")
print(f"dropped by GATE total:      {dropped:,}  ({100*dropped/TOTAL:.2f}% of formal graph)")
print(f"  - non-whitelisted kind:   {drop_kind:,}   e.g. {sorted(kindctr.items(),key=lambda x:-x[1])[:6]}")
print(f"  - compiler-internal name (kind ok): {drop_name:,}")
print(f"  (overlap kind&name: {both:,})")

# ---- manifest = the survivors actually written for the sweep ----
mrows=list(csv.DictReader(open(B+'TheoremSearch/experiments/nl_fl_matching/salient_discovery/data/query_manifest.csv')))
M=len(mrows)
# verify EVERY manifest row passes the gate (no artifact leaked through)
leak=0
for r in mrows:
    nk=KIND_NORM.get(r.get('kind',''),r.get('kind',''))
    if nk not in GATE_KINDS or is_internal(r.get('decl_name','')):
        leak+=1
print(f"\n--- MANIFEST (written sweep queries) ---")
print(f"manifest rows: {M:,}")
print(f"manifest rows FAILING the gate (leaks): {leak}   [should be 0]")

# ---- swept set ----
swept=set()
for line in open(B+'swept_sid_bin.tsv'):
    swept.add(line.split('\t')[0])
print(f"\n--- SWEPT (actually processed) ---")
print(f"swept nodes: {len(swept):,}")

print(f"\n=== RECONCILE ===")
print(f"gate survivors (over all {TOTAL:,}): {surv:,}")
print(f"manifest written:                   {M:,}")
print(f"swept:                              {len(swept):,}")
print(f"gate-survivors - manifest = {surv-M:,}  (embeddability/feature drop: nodes that pass gate but lack slogan/embedding/features)")
print(f"manifest - swept = {M-len(swept):,}")
