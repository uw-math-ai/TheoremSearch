import json, gc, numpy as np, torch, torch.nn.functional as F
from transformers import AutoModelForCausalLM, AutoModel, AutoTokenizer
W="/gscratch/amath/aurasoph/formalize_rag"
decls=json.load(open(f"{W}/bm_index_decls.json"))
SYS=("Given a Lean 4 formal theorem/definition signature, write a concise (1-2 sentence) "
     "INFORMAL mathematical description of what it states, in standard textbook prose. "
     "Do NOT use Lean syntax or identifier names; describe the mathematics. Output only the description. /no_think")
# --- back-translate with Qwen3-8B ---
tok=AutoTokenizer.from_pretrained("Qwen/Qwen3-8B", padding_side="left")
if tok.pad_token is None: tok.pad_token=tok.eos_token
lm=AutoModelForCausalLM.from_pretrained("Qwen/Qwen3-8B", torch_dtype=torch.bfloat16, device_map="cuda").eval()
def render(sig):
    m=[{"role":"system","content":SYS},{"role":"user","content":f"Signature of `{ '' }`:\n{sig}\n\nInformal description:"}]
    try: return tok.apply_chat_template(m,tokenize=False,add_generation_prompt=True,enable_thinking=False)
    except TypeError: return tok.apply_chat_template(m,tokenize=False,add_generation_prompt=True)
import re
def clean(t):
    t=re.sub(r"<think>.*?</think>"," ",t,flags=re.DOTALL).replace("<think>"," ").replace("</think>"," ")
    return " ".join(t.split())[:400]
informals=[None]*len(decls); B=24
for i in range(0,len(decls),B):
    ch=decls[i:i+B]; pr=[render(d["sig"]) for d in ch]
    enc=tok(pr,return_tensors="pt",padding=True,truncation=True,max_length=1024).to("cuda")
    with torch.no_grad(): g=lm.generate(**enc,max_new_tokens=120,do_sample=False,pad_token_id=tok.pad_token_id)
    for j,(d,full,inp) in enumerate(zip(ch,g,enc["input_ids"])):
        informals[i+j]=clean(tok.decode(full[inp.shape[0]:],skip_special_tokens=True))
    if i%240==0: print(f"backtrans {i+len(ch)}/{len(decls)}",flush=True)
for d,inf in zip(decls,informals): d["informal"]=inf
json.dump(decls, open(f"{W}/bm_informal.json","w"))
del lm; gc.collect(); torch.cuda.empty_cache()
# --- embed informals with Qwen3-Embedding-8B ---
etok=AutoTokenizer.from_pretrained("Qwen/Qwen3-Embedding-8B", padding_side="left")
emb=AutoModel.from_pretrained("Qwen/Qwen3-Embedding-8B", torch_dtype=torch.float16, device_map="cuda").eval()
@torch.no_grad()
def enc_e(texts):
    o=[]
    for i in range(0,len(texts),16):
        b=etok(texts[i:i+16],padding=True,truncation=True,max_length=256,return_tensors="pt").to("cuda")
        o.append(F.normalize(emb(**b).last_hidden_state[:,-1].float(),dim=-1).cpu().numpy())
    return np.concatenate(o)
np.save(f"{W}/bm_index_vecs.npy", enc_e(informals))
print("BM_BACKTRANS_EMBED_DONE", len(decls), flush=True)
