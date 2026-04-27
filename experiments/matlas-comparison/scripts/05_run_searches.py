"""Run all queries against TheoremSearch and MATLAS, capture full top-10.

Sequential with retries — concurrent calls saw transient ~20% failure rates
that look (incorrectly) like engine similarity thresholds. Sequential mode
recovers all of those.

Input:  ../data/queries.json
Output: ../results/search_full.json — each query with full top-10 from both engines.
"""
import json, urllib.request, time, os, sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
QUERIES = os.path.join(ROOT, "data", "queries.json")
OUT = os.path.join(ROOT, "results", "search_full.json")
K = 10
RETRIES = 3


def ts_search(q: str, k: int = K):
    last = ""
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(
                "https://api.theoremsearch.com/search",
                data=json.dumps({"query": q, "n_results": k}).encode(),
                headers={"Content-Type": "application/json"},
            )
            d = json.load(urllib.request.urlopen(req, timeout=60))
            return d.get("theorems", [])
        except Exception as e:
            last = str(e)
            time.sleep(2 * (attempt + 1))
    print(f"  TS gave up after {RETRIES}x: {last[:80]}", file=sys.stderr)
    return None


def matlas_search(q: str, k: int = K):
    last = ""
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(
                "https://matlas.ai/api/search",
                data=json.dumps({"query": q, "num_results": k}).encode(),
                headers={"Content-Type": "application/json"},
            )
            return json.load(urllib.request.urlopen(req, timeout=60))
        except Exception as e:
            last = str(e)
            time.sleep(2 * (attempt + 1))
    print(f"  MATLAS gave up after {RETRIES}x: {last[:80]}", file=sys.stderr)
    return None


def main():
    queries = json.load(open(QUERIES))
    print(f"Running {len(queries)} queries × 2 engines", flush=True)

    results: list[dict] = []
    for i, q in enumerate(queries):
        th = ts_search(q['query'])
        mh = matlas_search(q['query'])
        ts_top10 = [
            {"title": (t.get("paper", {}).get("title", "") or ""),
             "name": t.get("name", ""),
             "body": (t.get("body", "") or ""),
             "sim": t.get("similarity")}
            for t in (th or [])[:K]
        ]
        m_top10 = [
            {"title": (h.get("title", "") or ""),
             "authors": (h.get("authors", "") or ""),
             "entity": h.get("entity_name", ""),
             "statement": (h.get("statement", "") or "")}
            for h in (mh or [])[:K]
        ]
        results.append({**q, "ts_top10": ts_top10, "matlas_top10": m_top10})
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(queries)}", flush=True)
        time.sleep(0.1)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(results, f)
    print(f"DONE: {len(results)} results → {OUT}", flush=True)


if __name__ == "__main__":
    main()
