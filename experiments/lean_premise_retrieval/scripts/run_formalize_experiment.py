"""Run the compiler-in-the-loop formalization experiment: NL -> Lean 4 statement (no proof).

Replaces the interactive Claude-Code agent runs with a scripted Anthropic tool-use loop, one
per target. Four conditions (what the model may use):
  norag     : informal description only
  rag       : informal + retrieved premises (name+sig), already in the input json
  libsearch : informal + a `grep_library` tool over the corpus name::signature listing
  both      : premises + grep_library

Tools given to the model:
  typecheck(statement) : Lean well-formedness check (TC_CMD, default ../lean/tc_ml.sh); capped at --max-tc/target
  grep_library(pattern): (libsearch/both) grep the --listing file
  submit(statement)    : final answer, written to --out as {id: statement}

Requires: ANTHROPIC_API_KEY, and a built Mathlib reachable by tc_ml.sh (set MATHLIB_PROJECT).
Model via LPR_FORMALIZER_MODEL (default claude-sonnet-4-6).

    ANTHROPIC_API_KEY=... MATHLIB_PROJECT=/path/to/built-mathlib \
    python scripts/run_formalize_experiment.py --condition rag \
      --input results/large_corpus/ml30_rag.json \
      --out   results/large_corpus/ml30_out_rag.json
"""
import argparse, json, os, subprocess
from pathlib import Path

import anthropic

REPO = Path(__file__).resolve().parent.parent
TC_CMD = os.environ.get("TC_CMD", str(REPO / "lean" / "tc_ml.sh"))
MODEL = os.environ.get("LPR_FORMALIZER_MODEL", "claude-sonnet-4-6")

SYS = ("You formalize an informal mathematical statement into a SINGLE Lean 4 (Mathlib v4.30) "
       "theorem STATEMENT — no proof. Rules: name it `cand`; use FULLY-QUALIFIED names (no `open` "
       "is in scope); end with ` := sorry`; capture ALL hypotheses and the exact conclusion — do "
       "not weaken or trivialize. Use `typecheck` to check well-formedness (at most {k} times; a "
       "clean result shows only a `sorry` warning). When done, call `submit` with your best "
       "`theorem cand ... := sorry`. Do not read source or use #check/#print/#eval/import.")

TOOLS_BASE = [
    {"name": "typecheck", "description": "Typecheck a Lean statement for well-formedness.",
     "input_schema": {"type": "object", "properties": {"statement": {"type": "string"}},
                      "required": ["statement"]}},
    {"name": "submit", "description": "Submit the final `theorem cand ... := sorry`.",
     "input_schema": {"type": "object", "properties": {"statement": {"type": "string"}},
                      "required": ["statement"]}},
]
TOOL_GREP = {"name": "grep_library",
             "description": "Grep the Mathlib declaration listing (lines are `name<TAB>signature`).",
             "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}},
                              "required": ["pattern"]}}


def typecheck(stmt):
    try:
        r = subprocess.run(["bash", TC_CMD, stmt], capture_output=True, text=True, timeout=360)
        return (r.stdout + r.stderr).strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "TIMEOUT"


def grep_library(pattern, listing, limit=40):
    try:
        r = subprocess.run(["grep", "-iE", pattern, listing], capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    lines = r.stdout.splitlines()[:limit]
    return "\n".join(lines) if lines else "(no matches)"


def build_user(item, condition):
    s = f"Informal statement:\n{item['informal']}\n"
    if condition in ("rag", "both") and item.get("premises"):
        s += "\nRetrieved premises (name : signature):\n" + \
             "\n".join(f"- {p['name']} : {p['sig']}" for p in item["premises"])
    if condition in ("libsearch", "both"):
        s += "\n(You may also call grep_library to search the full library listing.)"
    return s


def run_one(client, item, condition, listing, max_tc):
    tools = list(TOOLS_BASE) + ([TOOL_GREP] if condition in ("libsearch", "both") else [])
    msgs = [{"role": "user", "content": build_user(item, condition)}]
    tc_used, best = 0, None
    for _ in range(2 * max_tc + 8):                       # safety bound on turns
        resp = client.messages.create(model=MODEL, max_tokens=2048,
                                      system=SYS.format(k=max_tc), tools=tools, messages=msgs)
        msgs.append({"role": "assistant", "content": resp.content})
        results, done = [], False
        for b in resp.content:
            if b.type != "tool_use":
                continue
            if b.name == "submit":
                best = b.input.get("statement", best); done = True
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": "recorded"})
            elif b.name == "typecheck":
                stmt = b.input["statement"]; best = best or stmt
                if tc_used >= max_tc:
                    out = "BUDGET EXHAUSTED — call submit with your best attempt."
                else:
                    tc_used += 1; out = typecheck(stmt)
                    if "error" not in out.lower():
                        best = stmt                       # well-formed (sorry warning only)
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": out})
            elif b.name == "grep_library":
                results.append({"type": "tool_result", "tool_use_id": b.id,
                                "content": grep_library(b.input["pattern"], listing)})
        if done:
            break
        msgs.append({"role": "user",
                     "content": results or "Call submit with your final `theorem cand ... := sorry`."})
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--condition", required=True, choices=["norag", "rag", "libsearch", "both"])
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--listing", default=str(REPO / "cache" / "ml429_namesigs.tsv"))
    ap.add_argument("--max-tc", type=int, default=3)
    args = ap.parse_args()

    client = anthropic.Anthropic()                        # reads ANTHROPIC_API_KEY
    items = json.loads(Path(args.input).read_text())
    out = {}
    for it in items:
        stmt = run_one(client, it, args.condition, args.listing, args.max_tc)
        out[it["id"]] = stmt or ""
        print(f"{it['id']}: {'ok' if stmt else 'EMPTY'}")
    Path(args.out).write_text(json.dumps(out, indent=1))
    print(f"wrote {args.out}  ({sum(bool(v) for v in out.values())}/{len(out)} non-empty)")


if __name__ == "__main__":
    main()
