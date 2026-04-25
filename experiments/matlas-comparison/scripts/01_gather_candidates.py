"""Gather arXiv candidates by journal-ref filter on MATLAS-covered journals.

For each journal × arXiv subject pair, queries the arXiv API and keeps papers
whose `journal-ref` field puts them in 2010-2021. arXiv enforces a ~3s rate
limit so this runs sequentially.

Output: ../data/candidates.json — {arxiv_id: {title, jr, cat, year, journal}}
"""
import urllib.request, urllib.parse, xml.etree.ElementTree as ET
import json, time, sys, os

JOURNALS = [
    ("Invent. Math.",            ["math.AG","math.NT","math.RT","math.GT","math.DG"]),
    ("Duke Math. J.",            ["math.AG","math.NT","math.GT","math.AP"]),
    ("Compos. Math.",            ["math.AG","math.NT","math.RT"]),
    ("J. Amer. Math. Soc.",      ["math.AG","math.NT","math.GT","math.RT"]),
    ("Adv. Math.",               ["math.AG","math.RT","math.CO","math.GT","math.NT"]),
    ("Acta Math.",               ["math.AG","math.AP","math.NT","math.DG"]),
    ("J. Algebraic Geom.",       ["math.AG"]),
    ("Geom. Topol.",             ["math.GT","math.AT","math.SG"]),
    ("Math. Ann.",               ["math.AG","math.AP","math.DG","math.NT","math.RT"]),
    ("Trans. Amer. Math. Soc.",  ["math.AG","math.NT","math.GT","math.CO","math.RT"]),
    ("J. Reine Angew. Math.",    ["math.AG","math.NT","math.DG"]),
    ("J. Eur. Math. Soc.",       ["math.AG","math.NT","math.GT"]),
    ("Geom. Funct. Anal.",       ["math.GT","math.DG","math.AP"]),
    ("Selecta Math.",            ["math.AG","math.RT","math.QA","math.CO"]),
    ("Math. Z.",                 ["math.AG","math.NT","math.GT","math.RT"]),
    ("Internat. Math. Res. Notices", ["math.AG","math.NT","math.RT","math.CO"]),
    ("Int. Math. Res. Not.",     ["math.AG","math.NT"]),
    ("Algebra Number Theory",    ["math.AG","math.NT"]),
    ("Comm. Math. Phys.",        ["math.QA","math.RT","math.SG"]),
    ("Ann. of Math.",            ["math.AG","math.NT","math.GT"]),
]
YEAR_WINDOW = range(2010, 2022)
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "candidates.json")
NS = {'a':'http://www.w3.org/2005/Atom', 'arxiv':'http://arxiv.org/schemas/atom'}


def fetch_journal_cat(journal: str, cat: str, max_results: int = 30):
    q = f'jr:"{journal}" AND cat:{cat}'
    params = urllib.parse.urlencode({
        "search_query": q,
        "max_results": str(max_results),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    url = f"https://export.arxiv.org/api/query?{params}"
    return urllib.request.urlopen(url, timeout=30).read()


def parse_entries(xml_data: bytes):
    root = ET.fromstring(xml_data)
    for entry in root.findall('a:entry', NS):
        aid = entry.find('a:id', NS).text.split('/')[-1].split('v')[0]
        title = ' '.join(entry.find('a:title', NS).text.split())
        jr_el = entry.find('arxiv:journal_ref', NS)
        jr = jr_el.text if jr_el is not None else ''
        yield aid, title, jr


def main():
    candidates: dict[str, dict] = {}
    for journal, cats in JOURNALS:
        for cat in cats:
            try:
                data = fetch_journal_cat(journal, cat)
            except Exception as e:
                print(f"err {journal}/{cat}: {e}", file=sys.stderr)
                time.sleep(3.2); continue
            n_added = 0
            for aid, title, jr in parse_entries(data):
                year = next((y for y in YEAR_WINDOW if str(y) in jr), None)
                if year is None or aid in candidates:
                    continue
                candidates[aid] = {
                    'title': title, 'jr': jr, 'cat': cat,
                    'year': year, 'journal': journal,
                }
                n_added += 1
            print(f"[{journal}/{cat}] +{n_added} (total {len(candidates)})", flush=True)
            time.sleep(3.2)  # arXiv API rate limit

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(candidates, f, indent=1)
    print(f"DONE: {len(candidates)} unique candidates → {OUT_PATH}", flush=True)


if __name__ == "__main__":
    main()
