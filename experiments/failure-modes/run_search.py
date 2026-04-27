"""
Hit POST /search for every query in queries.jsonl and dump raw responses.

Input  : data/queries.jsonl  (one JSON per line: {id, category, query, pair_id?, intent})
Output : results/raw.jsonl   (one JSON per line: {id, query, theorems: [...], elapsed_ms})
"""
import json
import time
import urllib.request
import urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path(__file__).parent
QUERIES = ROOT / "data" / "queries.jsonl"
OUT = ROOT / "results" / "raw.jsonl"
N_RESULTS = 10
WORKERS = 6


def search(query: str, n: int = N_RESULTS) -> dict:
    payload = json.dumps({"query": query, "n_results": n}).encode()
    req = urllib.request.Request(
        "https://api.theoremsearch.com/search",
        headers={"Content-Type": "application/json"},
        data=payload,
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            body = json.loads(r.read())
        return {"theorems": body.get("theorems", []), "elapsed_ms": int((time.time() - t0) * 1000)}
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        return {"theorems": [], "elapsed_ms": int((time.time() - t0) * 1000), "error": str(e)}


def main():
    rows = [json.loads(l) for l in QUERIES.read_text().splitlines() if l.strip()]
    OUT.parent.mkdir(parents=True, exist_ok=True)

    out_rows = [None] * len(rows)

    def work(i, row):
        res = search(row["query"])
        return i, {**row, **res}

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = [ex.submit(work, i, r) for i, r in enumerate(rows)]
        done = 0
        for fut in as_completed(futures):
            i, res = fut.result()
            out_rows[i] = res
            done += 1
            if done % 10 == 0:
                print(f"{done}/{len(rows)}", flush=True)

    with OUT.open("w") as f:
        for r in out_rows:
            f.write(json.dumps(r) + "\n")
    print(f"wrote {len(out_rows)} rows to {OUT}")


if __name__ == "__main__":
    main()
