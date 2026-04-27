"""
Re-judge every raw retrieval row on a -2..+2 scale and write a readable CSV.

Inputs : results/raw_all.jsonl, results/raw_d.jsonl
Outputs: results/judged_scored.jsonl  (one JSON per row)
         failure_modes.csv             (query, intent, category, score, judgement, top_1..top_3)

Score scale (model is asked to pick exactly one):
  +2  perfect       — top‑1 is a clear, on-target match for the intent
  +1  good          — a clear match exists in top‑3 but not at rank 1
   0  partial       — tangentially related; nothing in top‑3 directly answers
  -1  bad           — top‑3 is off-topic / wrong-named result
  -2  garbage       — meta/corrupted slogans or retrieval failure
"""
import csv
import json
import os
import urllib.request
import urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path(__file__).parent
RAW_FILES = [ROOT / "results" / "raw_all.jsonl", ROOT / "results" / "raw_d.jsonl"]
JSONL_OUT = ROOT / "results" / "judged_scored.jsonl"
CSV_OUT = ROOT / "failure_modes.csv"
TOP_K = 5
MODEL = "gpt-5.4-mini"
WORKERS = 16


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

Score the *retrieval as a whole* — does the top of the list serve the searcher?

Use this scale exactly:
  +2  perfect — top‑1 is a clear, on-target match
  +1  good    — a clear match appears in top‑3 but not at rank 1
   0  partial — only tangentially related; nothing in top‑3 directly answers
  -1  bad     — top‑3 is off-topic or wrong-named result
  -2  garbage — meta/corrupted slogans (e.g. "the theorem is not interpretable",
                "this theorem holds", "main theorem implies main theorem"),
                or no useful retrieval at all

Return strict JSON: {{"score": <-2|-1|0|1|2>, "reason": "<=25 words", "best_rank": <1..K or null>}}
"""


def judge(row: dict) -> dict:
    slogans = []
    for i, t in enumerate(row.get("theorems", [])[:TOP_K]):
        s = (t.get("slogan") or t.get("body") or "")[:300]
        slogans.append(f"{i+1}. {s}")
    if not slogans:
        return {**row, "score": -2, "reason": "no results returned", "best_rank": None}

    prompt = PROMPT.format(
        query=row["query"],
        intent=row.get("intent", "(no intent given)"),
        k=len(slogans),
        slogans="\n".join(slogans),
    )
    try:
        verdict = json.loads(chat(prompt))
        score = verdict.get("score")
        if score not in (-2, -1, 0, 1, 2):
            score = 0
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
        return {**row, "score": None, "reason": f"judge error: {str(e)[:60]}", "best_rank": None}
    return {**row, "score": score, "reason": verdict.get("reason", ""), "best_rank": verdict.get("best_rank")}


def main():
    rows = []
    for p in RAW_FILES:
        if p.exists():
            rows.extend(json.loads(l) for l in p.read_text().splitlines() if l.strip())
    print(f"loaded {len(rows)} rows from {len(RAW_FILES)} files")

    JSONL_OUT.parent.mkdir(parents=True, exist_ok=True)
    judged = [None] * len(rows)
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(judge, r): i for i, r in enumerate(rows)}
        done = 0
        for fut in as_completed(futures):
            i = futures[fut]
            judged[i] = fut.result()
            done += 1
            if done % 50 == 0:
                print(f"{done}/{len(rows)}", flush=True)

    with JSONL_OUT.open("w") as f:
        for r in judged:
            slim = {k: v for k, v in r.items() if k != "theorems"}
            slim["top_slogans"] = [
                (t.get("slogan") or t.get("body") or "")[:300] for t in r.get("theorems", [])[:TOP_K]
            ]
            f.write(json.dumps(slim) + "\n")
    print(f"wrote {JSONL_OUT}")

    with CSV_OUT.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["category", "pair_id", "query", "intent", "score", "best_rank", "judgement", "top_1", "top_2", "top_3"])
        for r in judged:
            tops = [(t.get("slogan") or t.get("body") or "").replace("\n", " ").strip()[:280]
                    for t in r.get("theorems", [])[:3]]
            tops += [""] * (3 - len(tops))
            w.writerow([
                r.get("category", ""),
                r.get("pair_id", ""),
                r["query"],
                r.get("intent", ""),
                r.get("score"),
                r.get("best_rank"),
                r.get("reason", ""),
                *tops,
            ])
    print(f"wrote {CSV_OUT}")


if __name__ == "__main__":
    main()
