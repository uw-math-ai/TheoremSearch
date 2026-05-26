"""Judge correctness of formalizer outputs against the gold declarations.

For each id, asks the judge model to compare the candidate statement to the real Mathlib
declaration's signature and label it:
  strict     = exactly the same proposition
  equivalent = almost certainly logically equivalent, but a non-trivial restatement
  wrong      = different / weaker / stronger proposition, or wrong object
Writes a per-id CSV and prints the summary used in the paper:
  strict ✓                = count(strict)
  evaluated correct       = count(strict) + count(equivalent)

Requires ANTHROPIC_API_KEY. Model via LPR_JUDGE_MODEL (default claude-opus-4-7).

    ANTHROPIC_API_KEY=... python scripts/judge_correctness.py \
      --out-json results/large_corpus/ml30_out_rag.json \
      --refs     results/large_corpus/ml30_refs.json \
      --idmap    results/large_corpus/ml30_idmap.json \
      --report   results/large_corpus/judge_rag.csv
"""
import argparse, csv, json, os, re
from pathlib import Path

import anthropic

MODEL = os.environ.get("LPR_JUDGE_MODEL", "claude-opus-4-7")

PROMPT = """Judge whether a candidate Lean 4 statement expresses the SAME mathematical proposition
as the gold declaration (the real Mathlib theorem). Both end in `sorry`; ignore proofs. Binder /
notation / universe differences and provably-equivalent restatements are acceptable; a different,
weaker, stronger, or wrong-object statement is not.

GOLD (real declaration signature):
{gold}

CANDIDATE:
{cand}

Respond with ONLY a JSON object:
{{"label": "strict" | "equivalent" | "wrong", "reason": "<one short line>"}}
  strict     = exactly the same proposition
  equivalent = almost certainly logically equivalent but a non-trivial restatement to verify
  wrong      = a different / weaker / stronger proposition, or wrong object"""


def judge(client, gold, cand):
    if not cand.strip():
        return "wrong", "empty output"
    r = client.messages.create(model=MODEL, max_tokens=400,
                               messages=[{"role": "user",
                                          "content": PROMPT.format(gold=gold, cand=cand)}])
    txt = "".join(b.text for b in r.content if b.type == "text")
    m = re.search(r"\{.*\}", txt, re.DOTALL)
    try:
        d = json.loads(m.group(0))
        return d.get("label", "wrong"), d.get("reason", "")
    except Exception:
        return "wrong", "unparseable: " + txt[:80].replace("\n", " ")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-json", required=True)          # ml30_out_<cond>.json : {id: statement}
    ap.add_argument("--refs", required=True)              # ml30_refs.json       : {decl_name: gold sig}
    ap.add_argument("--idmap", required=True)             # ml30_idmap.json      : {id: decl_name}
    ap.add_argument("--report", required=True)
    a = ap.parse_args()

    client = anthropic.Anthropic()
    outs = json.loads(Path(a.out_json).read_text())
    refs = json.loads(Path(a.refs).read_text())
    idmap = json.loads(Path(a.idmap).read_text())

    rows, strict, equiv = [], 0, 0
    for tid, cand in outs.items():
        name = idmap.get(tid, tid)
        label, reason = judge(client, refs.get(name, ""), cand)
        strict += label == "strict"
        equiv += label == "equivalent"
        rows.append({"id": tid, "name": name, "label": label, "reason": reason})
        print(f"{tid:5} {label:10} {name}")

    with open(a.report, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "name", "label", "reason"])
        w.writeheader(); w.writerows(rows)
    n = len(outs)
    print(f"\n{a.out_json}: strict {strict}/{n}  |  evaluated correct (strict+equivalent) {strict + equiv}/{n}")
    print(f"per-item labels -> {a.report}")


if __name__ == "__main__":
    main()
