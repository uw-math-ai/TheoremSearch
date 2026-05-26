"""P3: generate formal statements from slogans, no-RAG vs RAG, for one model.

Runs inside the vLLM apptainer (which carries torch+transformers) on an L40S.
Reads the eval set with retrieved premises; for each target builds two prompts
(no-RAG: slogan only; RAG: slogan + retrieved premise names) and generates the
Lean proposition TYPE only (the contract run_typecheck.py expects). Writes
{tid: {"no_rag": str, "rag": str}} to --out.

Model is loaded OFFLINE from a shared HF cache (no internet on compute nodes).

    HF_HOME=/gscratch/amath/kogolobo/hf_home HF_HUB_OFFLINE=1 \
      python formalize_gen.py --model Qwen/Qwen3.5-4B --eval eval.pkl --out out.json
"""
import argparse
import json
import pickle
import re

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

SYS = ("You are an expert in Lean 4 and Mathlib. Given an informal description "
       "of a theorem, write its formal statement as ONE complete Lean 4 "
       "declaration of the form `theorem foo <binders> : <type> := sorry`. "
       "Bind every variable with explicit binders or with forall in the type. "
       "Output ONLY the single declaration on one line, ending in ` := sorry`. "
       "No explanation, no comments, no markdown, no code fences. /no_think")


def build_msgs(slogan, retrieved=None):
    u = f"Informal statement: {slogan}\n"
    if retrieved:
        names = ", ".join(n for n in retrieved if n)
        u += f"\nRelevant Mathlib declarations you may need: {names}\n"
    u += "\nLean 4 declaration:"
    return [{"role": "system", "content": SYS}, {"role": "user", "content": u}]


def clean(text):
    # drop reasoning, fences, markdown; return the theorem declaration line
    text = re.sub(r"<think>.*?</think>", " ", text, flags=re.DOTALL)
    text = text.replace("<think>", " ").replace("</think>", " ")
    text = re.sub(r"```(?:lean4?|)", " ", text).replace("**", " ")
    # prefer a line that starts a declaration; else first non-trivial line
    decl = None
    for line in text.splitlines():
        line = line.strip()
        if re.match(r"^(theorem|lemma|example|def)\b", line):
            decl = line; break
    if decl is None:
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("--") and not line.lower().startswith("lean"):
                decl = line; break
    return (decl or text.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--eval", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max_new", type=int, default=512)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    ev = pickle.load(open(args.eval, "rb"))
    tids = list(ev)
    if args.limit:
        tids = tids[:args.limit]
    print(f"loaded {len(tids)} targets; loading {args.model}...", flush=True)

    tok = AutoTokenizer.from_pretrained(args.model, padding_side="left")
    model = AutoModelForCausalLM.from_pretrained(
        args.model, torch_dtype=torch.bfloat16, device_map="cuda")
    model.eval()
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    def render(msgs):
        try:
            return tok.apply_chat_template(msgs, tokenize=False,
                                           add_generation_prompt=True,
                                           enable_thinking=False)
        except TypeError:
            return tok.apply_chat_template(msgs, tokenize=False,
                                           add_generation_prompt=True)

    # one flat list: (tid, cond, prompt)
    jobs = []
    for t in tids:
        jobs.append((t, "no_rag", render(build_msgs(ev[t]["slogan"]))))
        jobs.append((t, "rag", render(build_msgs(ev[t]["slogan"], ev[t]["retrieved"]))))

    out = {t: {} for t in tids}
    for i in range(0, len(jobs), args.batch):
        chunk = jobs[i:i + args.batch]
        prompts = [p for _, _, p in chunk]
        enc = tok(prompts, return_tensors="pt", padding=True,
                  truncation=True, max_length=2048).to("cuda")
        with torch.no_grad():
            gen = model.generate(**enc, max_new_tokens=args.max_new,
                                 do_sample=False, pad_token_id=tok.pad_token_id)
        for (t, cond, _), full, inp in zip(chunk, gen, enc["input_ids"]):
            comp = tok.decode(full[inp.shape[0]:], skip_special_tokens=True)
            out[t][cond] = clean(comp)
        if (i // args.batch) % 10 == 0:
            print(f"  {i+len(chunk)}/{len(jobs)}", flush=True)

    json.dump(out, open(args.out, "w"))
    print(f"wrote {args.out}", flush=True)


if __name__ == "__main__":
    main()
