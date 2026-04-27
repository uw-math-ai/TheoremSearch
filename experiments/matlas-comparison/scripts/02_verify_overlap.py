"""For each candidate, verify presence in BOTH engines via metadata only.

- TheoremSearch: hit /paper-search?q=<arxiv_id>, confirm exact `external_id` match.
- MATLAS: query the paper title via /api/search, confirm an exact-or-substring
  title match in any of the top-50 results.

Both checks are metadata-level, NOT theorem-content-level — this avoids biasing
the downstream comparison toward papers either engine handles well.

Input:  ../data/candidates.json
Output: ../data/confirmed.json — subset confirmed in both engines.
"""
import json, urllib.request, time, re, os, sys
import concurrent.futures, threading

ROOT = os.path.join(os.path.dirname(__file__), "..", "data")
IN_PATH = os.path.join(ROOT, "candidates.json")
OUT_PATH = os.path.join(ROOT, "confirmed.json")


def norm_title(t: str) -> str:
    t = (t or "").lower()
    t = re.sub(r"[\$\\{}]", "", t)
    t = re.sub(r"[-/]", " ", t)
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def ts_check(arxiv_id: str):
    try:
        url = f"https://api.theoremsearch.com/paper-search?q={arxiv_id}&limit=3"
        d = json.load(urllib.request.urlopen(url, timeout=15))
        for p in d.get('papers', []):
            if p.get('external_id') == arxiv_id:
                return True, p['title']
    except Exception as e:
        return None, str(e)
    return False, None


def matlas_check(title: str):
    try:
        req = urllib.request.Request(
            "https://matlas.ai/api/search",
            data=json.dumps({"query": title, "num_results": 50}).encode(),
            headers={"Content-Type": "application/json"},
        )
        hits = json.load(urllib.request.urlopen(req, timeout=20))
    except Exception as e:
        return None, str(e)
    nt = norm_title(title)
    for h in hits:
        if h.get('type') != 'paper':
            continue
        ht = norm_title(h.get('title', ''))
        if not ht:
            continue
        if ht == nt:
            return True, (h.get('title',''), h.get('authors',''), h.get('journal',''), h.get('year',''))
        if len(ht) > 15 and ht in nt:
            return True, (h.get('title',''), h.get('authors',''), h.get('journal',''), h.get('year',''))
        if len(nt) > 15 and nt in ht:
            return True, (h.get('title',''), h.get('authors',''), h.get('journal',''), h.get('year',''))
    return False, None


def process(item):
    aid, meta = item
    ts_ok, ts_info = ts_check(aid)
    if not ts_ok:
        return None
    m_ok, m_info = matlas_check(meta['title'])
    if not m_ok:
        return None
    return aid, {**meta, 'ts_title': ts_info, 'matlas_info': m_info}


def main():
    cands = json.load(open(IN_PATH))
    print(f"Verifying {len(cands)} candidates", flush=True)

    confirmed: dict[str, dict] = {}
    items = list(cands.items())
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        futures = [ex.submit(process, it) for it in items]
        for i, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            r = fut.result()
            if r:
                confirmed[r[0]] = r[1]
            if i % 25 == 0:
                print(f"  {i}/{len(items)} processed, {len(confirmed)} confirmed", flush=True)

    with open(OUT_PATH, "w") as f:
        json.dump(confirmed, f, indent=1)
    print(f"DONE: {len(confirmed)} confirmed papers → {OUT_PATH}", flush=True)


if __name__ == "__main__":
    main()
