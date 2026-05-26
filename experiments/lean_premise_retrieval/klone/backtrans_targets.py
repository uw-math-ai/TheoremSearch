import json, gc, numpy as np, torch, torch.nn.functional as F, re
from transformers import AutoModelForCausalLM, AutoModel, AutoTokenizer
W="/gscratch/amath/aurasoph/formalize_rag"
targets=json.load(open(f"{W}/ml_run_targets.json"))   # [{name, module, sig, premises}]
SYS=("Given a Lean 4 formal theorem signature, write a concise (1-2 sentence) INFORMAL "
     "mathematical description of what it states, in standard textbook prose. Do NOT use Lean "
     "syntax or identifier names; describe the mathematics. Output only the description. /no_think")

tok=AutoTokenizer.from_pretrained("Qwen/Qwen3-8B", padding_side="left")
if tok.pad_token is None: tok.pad_token=tok.eos_token
lm=AutoModelForCausalLM.from_pretrained("Qwen/Qwen3-8B", torch_dtype=torch.bfloat16, device_map="cuda").eval()
def render(sig):
    # name deliberately blanked so it can't leak into the informal description
    m=[{"role":"system","content":SYS},{"role":"user","content":f"Signature:\n{sig}\n\nInformal description:"}]
    try: return tok.apply_chat_template(m,tokenize=False,add_generation_prompt=True,enable_thinking=False)
    except TypeError: return tok.apply_chat_template(m,tokenize=False,add_generation_prompt=True)
def clean(t):
    t=re.sub(r"<think>.*?</think>"," ",t,flags=re.DOTALL).replace("<think>"," ").replace("</think>"," ")
    return " ".join(t.split())[:400]
informals=[None]*len(targets); B=16
for i in range(0,len(targets),B):
    ch=targets[i:i+B]; pr=[render(d["sig"]) for d in ch]
    enc=tok(pr,return_tensors="pt",padding=True,truncation=True,max_length=1024).to("cuda")
    with torch.no_grad(): g=lm.generate(**enc,max_new_tokens=120,do_sample=False,pad_token_id=tok.pad_token_id)
    for j,(d,full,inp) in enumerate(zip(ch,g,enc["input_ids"])):
        informals[i+j]=clean(tok.decode(full[inp.shape[0]:],skip_special_tokens=True))
    print(f"backtrans {i+len(ch)}/{len(targets)}",flush=True)
for d,inf in zip(targets,informals): d["informal"]=inf
json.dump(targets, open(f"{W}/ml_targets_informal.json","w"))
del lm; gc.collect(); torch.cuda.empty_cache()

etok=AutoTokenizer.from_pretrained("Qwen/Qwen3-Embedding-8B", padding_side="left")
emb=AutoModel.from_pretrained("Qwen/Qwen3-Embedding-8B", torch_dtype=torch.float16, device_map="cuda").eval()
@torch.no_grad()
def enc_e(texts):
    o=[]
    for i in range(0,len(texts),16):
        b=etok(texts[i:i+16],padding=True,truncation=True,max_length=256,return_tensors="pt").to("cuda")
        o.append(F.normalize(emb(**b).last_hidden_state[:,-1].float(),dim=-1).cpu().numpy())
    return np.concatenate(o)
np.save(f"{W}/ml_targets_qvecs.npy", enc_e(informals))
print("ML_TARGETS_BACKTRANS_EMBED_DONE", len(targets), flush=True)
