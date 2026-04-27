"""
For every query in results/raw.jsonl, ask GPT to judge top-K slogans:
  verdict ∈ {good, partial, bad}
  reason  : <= 25 words, says why
Writes results/judged.jsonl.
"""
import json
import os
import urllib.request
import urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path(__file__).parent
RAW = ROOT / "results" / "raw_all.jsonl"
OUT = ROOT / "results" / "judged.jsonl"
TOP_K = 5
MODEL = "gpt-4o-mini"
WORKERS = 8


def load_key():
    for line in (ROOT.parent.parent / ".env").read_text().splitlines():
        if line.startswith("OPENAI_API_KEY"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("no OPENAI_API_KEY")


KEY = load_key()


def chat(prompt: str) -> str:
    payload = json.dumps(
        {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": "You are a precise judge of mathematical search relevance. Output strict JSON."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
    ).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
        data=payload,
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]


PROMPT = """Query: {query}
Stated intent (what the searcher likely wants): {intent}

Top {k} retrieved slogans:
{slogans}

Score the *retrieval as a whole*, considering whether the top results match the intent.

verdict semantics:
- "good"    : top-3 contains a clearly correct match (the named theorem / a near-statement / a closely-related result)
- "partial" : top-3 has tangentially-related material but no clear match; intent is partially served
- "bad"     : top-3 is off-topic / wrong-named result / clearly garbage

Return strict JSON: {{"verdict": "good|partial|bad", "reason": "<=25 words", "best_rank": <1..K or null if none relevant>}}
"""


def judge(row: dict) -> dict:
    slogans = []
    for i, t in enumerate(row.get("theorems", [])[:TOP_K]):
        s = (t.get("slogan") or t.get("body") or "")[:300]
        slogans.append(f"{i+1}. {s}")
    if not slogans:
        return {**row, "verdict": "bad", "reason": "no results returned", "best_rank": None}

    prompt = PROMPT.format(
        query=row["query"],
        intent=row.get("intent", "(no intent given)"),
        k=len(slogans),
        slogans="\n".join(slogans),
    )
    try:
        verdict = json.loads(chat(prompt))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
        verdict = {"verdict": "error", "reason": str(e)[:80], "best_rank": None}
    return {**row, **{k: verdict.get(k) for k in ("verdict", "reason", "best_rank")}}


def main():
    rows = [json.loads(l) for l in RAW.read_text().splitlines() if l.strip()]
    OUT.parent.mkdir(parents=True, exist_ok=True)

    judged = [None] * len(rows)
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(judge, r): i for i, r in enumerate(rows)}
        done = 0
        for fut in as_completed(futures):
            i = futures[fut]
            judged[i] = fut.result()
            done += 1
            if done % 20 == 0:
                print(f"{done}/{len(rows)}", flush=True)

    with OUT.open("w") as f:
        for r in judged:
            slim = {k: v for k, v in r.items() if k != "theorems"}
            slim["top_slogans"] = [
                (t.get("slogan") or t.get("body") or "")[:200] for t in r.get("theorems", [])[:TOP_K]
            ]
            f.write(json.dumps(slim) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
