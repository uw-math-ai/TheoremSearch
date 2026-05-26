import json, re, subprocess, tempfile, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_typecheck import _wrap
BM=os.environ.get("LPR_LIB_DIR", "/home/aurasl/projects/lean-repos/brownian-motion-v430-rc2")
HEADER=["import BrownianMotion","open MeasureTheory ProbabilityTheory Finset Topology NNReal",""]
def tc(stmts):
    lines=list(HEADER); ln={}
    for i,s in enumerate(stmts):
        lines.append(_wrap(i,s)); ln[i]=len(lines)
    f=tempfile.NamedTemporaryFile("w",suffix=".lean",dir="/tmp",delete=False); f.write("\n".join(lines)+"\n"); f.close()
    p=subprocess.run(["lake","env","lean",f.name],cwd=BM,capture_output=True,text=True,timeout=2400)
    out=p.stdout+p.stderr; bad=set()
    for m in re.finditer(rf"{re.escape(f.name)}:(\d+):\d+: error(?:\([^)]*\))?:",out): bad.add(int(m.group(1)))
    return [ln[i] not in bad for i in range(len(stmts))]
nr=json.load(open("cache/sonnet_bm_norag.json")); rg=json.load(open("cache/sonnet_bm_rag.json"))
names=list(nr.keys())
print("typechecking no_rag...",flush=True); tnr=tc([nr[n] for n in names])
print("typechecking rag...",flush=True);   trg=tc([rg[n] for n in names])
import statistics as st
print(f"\n=== SANDBOXED SONNET ±RAG on unfamiliar library (brownian-motion), typecheck rate ===")
print(f"  no-RAG: {sum(tnr)}/{len(tnr)} = {st.mean(tnr):.2f}")
print(f"  RAG:    {sum(trg)}/{len(trg)} = {st.mean(trg):.2f}")
print("\nper-problem (noRAG / RAG):")
for i,n in enumerate(names):
    print(f"  [{'T' if tnr[i] else 'F'} / {'T' if trg[i] else 'F'}] {n}")
json.dump({"names":names,"norag":tnr,"rag":trg}, open("cache/sonnet_bm_tc.json","w"))
