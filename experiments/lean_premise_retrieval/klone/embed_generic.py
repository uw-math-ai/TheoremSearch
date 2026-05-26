import json, sys, numpy as np, torch, torch.nn.functional as F
from transformers import AutoModel, AutoTokenizer
W="/gscratch/amath/aurasoph/formalize_rag"
inp, outp = sys.argv[1], sys.argv[2]
samp=json.load(open(f"{W}/{inp}"))
tok=AutoTokenizer.from_pretrained("Qwen/Qwen3-Embedding-8B", padding_side="left")
model=AutoModel.from_pretrained("Qwen/Qwen3-Embedding-8B", torch_dtype=torch.float16, device_map="cuda").eval()
@torch.no_grad()
def enc(texts):
    o=[]
    for i in range(0,len(texts),16):
        b=tok(texts[i:i+16],padding=True,truncation=True,max_length=512,return_tensors="pt").to("cuda")
        o.append(F.normalize(model(**b).last_hidden_state[:,-1].float(),dim=-1).cpu().numpy())
    return np.concatenate(o)
np.save(f"{W}/{outp}", enc([r["informal"] for r in samp])); print("EMBED_GENERIC_DONE", len(samp))
