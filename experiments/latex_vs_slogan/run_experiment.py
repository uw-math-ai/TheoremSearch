"""Stage 2: generate a slogan + an independent NL query per theorem, embed, score.

For each theorem we compare two *corpus* representations against a natural-language
query: the verbatim raw-LaTeX statement vs. an LLM-generated slogan. We score under
two prompt configurations:

  asym : query gets the query-instruction, candidates get the corpus-instruction
         (this is the deployed retriever's asymmetric setup).
  symq : both sides get the query-instruction (symmetric).

gap = cos(query, slogan) - cos(query, raw);  gap > 0 means the slogan is closer.

Writes data/results.json and prints the summary.
"""
import os, re, json, time
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from common import client, CHAT_MODEL, wrap, embed

DATA = os.path.join(os.path.dirname(__file__), "data")

SLOGAN_SYS = (
    "You are given a theorem statement extracted from a mathematics paper (in LaTeX). "
    "Produce a SLOGAN: a single concise, standalone, natural-language sentence stating what the "
    "theorem asserts. Name the mathematical objects but write in prose. Do NOT include LaTeX commands, "
    "dollar signs, \\cite, or labels. Output ONLY the slogan sentence, nothing else.")
QUERY_SYS = (
    "You are given a theorem statement from a mathematics paper (in LaTeX). Imagine a researcher who "
    "half-remembers this result and types a search query to find it. Write a 1-2 sentence plain-English "
    "description of the result's mathematical content. Do NOT use any formulas, symbols, LaTeX, or variable "
    "names; describe the meaning in words. Output ONLY the description, nothing else.")


def clean_raw(s):
    s = re.sub(r"\\label(\[[^\]]*\])?\{[^}]*\}", "", s)
    s = re.sub(r"\\qed\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def chat(sys_prompt, stmt, temp=0.3):
    for attempt in range(4):
        try:
            r = client.chat.completions.create(
                model=CHAT_MODEL, temperature=temp, max_tokens=220,
                messages=[{"role": "system", "content": sys_prompt},
                          {"role": "user", "content": stmt}])
            t = r.choices[0].message.content.strip()
            return re.sub(r"^```.*?\n|```$", "", t).strip()
        except Exception:
            time.sleep(2 + 2 * attempt)
    return ""


def main():
    papers = json.load(open(os.path.join(DATA, "papers.json")))
    items = [{"category": p["category"], "arxiv_id": p["arxiv_id"], "env": t["env"],
              "raw": clean_raw(t["statement"])}
             for p in papers for t in p["theorems"]]
    print("theorems:", len(items), flush=True)

    def gen(i):
        items[i]["slogan"] = chat(SLOGAN_SYS, items[i]["raw"])
        items[i]["query"] = chat(QUERY_SYS, items[i]["raw"])
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(gen, i) for i in range(len(items))]
        for n, _ in enumerate(as_completed(futs), 1):
            if n % 10 == 0:
                print("  gen", n, "/", len(items), flush=True)
    items = [it for it in items if it.get("slogan") and it.get("query")]
    print("after gen:", len(items), flush=True)

    texts, idx = [], {}
    def add(key, txt):
        idx[key] = len(texts); texts.append(txt)
    for i, it in enumerate(items):
        add((i, "query_Q"), wrap(it["query"], "query"))
        add((i, "raw_C"), wrap(it["raw"], "corpus"))
        add((i, "raw_Q"), wrap(it["raw"], "query"))
        add((i, "slo_C"), wrap(it["slogan"], "corpus"))
        add((i, "slo_Q"), wrap(it["slogan"], "query"))
    print("embedding", len(texts), "strings...", flush=True)
    vecs = embed(texts)
    V = lambda i, k: vecs[idx[(i, k)]]
    cos = lambda a, b: float(np.dot(a, b))

    for i, it in enumerate(items):
        q = V(i, "query_Q")
        it["asym_raw"], it["asym_slo"] = cos(q, V(i, "raw_C")), cos(q, V(i, "slo_C"))
        it["symq_raw"], it["symq_slo"] = cos(q, V(i, "raw_Q")), cos(q, V(i, "slo_Q"))
        it["asym_gap"] = it["asym_slo"] - it["asym_raw"]
        it["symq_gap"] = it["symq_slo"] - it["symq_raw"]
    json.dump(items, open(os.path.join(DATA, "results.json"), "w"), ensure_ascii=False, indent=1)

    def report(tag):
        gaps = np.array([it[tag + "_gap"] for it in items])
        slo = np.array([it[tag + "_slo"] for it in items])
        raw = np.array([it[tag + "_raw"] for it in items])
        print(f"\n== CONFIG {tag} ==  slogan-closer={np.mean(gaps > 0):.1%}  "
              f"mean gap={gaps.mean():+.4f}  median={np.median(gaps):+.4f}  "
              f"slo={slo.mean():.4f} raw={raw.mean():.4f}")
        for c in sorted(set(it["category"] for it in items)):
            g = np.array([it[tag + "_gap"] for it in items if it["category"] == c])
            print(f"     {c:9s} n={len(g):2d}  {np.mean(g > 0):5.0%}  {g.mean():+.4f}")
    report("asym")
    report("symq")
    print("\nDONE")


if __name__ == "__main__":
    main()
