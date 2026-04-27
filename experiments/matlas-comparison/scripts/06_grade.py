"""Grade each query at paper-level and theorem-level retrieval@k.

Paper-level match: normalized titles equal OR one is a contiguous substring
of the other (≥15 chars). Rejects look-alike titles like "On the De Rham-Witt
complex in mixed characteristic" being credited as a hit for the target
"The big de Rham-Witt complex".

Theorem-level match: paper-level match AND candidate body shares ≥ 2 normalized
word-4-grams with target theorem body. Robust to LaTeX macro expansion / OCR
variation between arXiv source and journal-published versions.

Input:  ../data/picks.json, ../results/search_full.json
Output: ../results/graded_full.json (per-query ranks)
        ../results/results.csv     (flat tabular)
        prints summary tables to stdout
"""
import json, re, os, csv

ROOT = os.path.join(os.path.dirname(__file__), "..")
PICKS = os.path.join(ROOT, "data", "picks.json")
SEARCH = os.path.join(ROOT, "results", "search_full.json")
GRADED = os.path.join(ROOT, "results", "graded_full.json")
CSV_OUT = os.path.join(ROOT, "results", "results.csv")


def norm_text(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"\\[a-zA-Z]+\*?\s*", " ", s)        # strip latex commands
    s = re.sub(r"[\\${}\[\]_^~]", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def ngrams(s: str, n: int) -> set[str]:
    ws = norm_text(s).split()
    if n == 1:
        return {w for w in ws if len(w) > 2}
    return {" ".join(ws[i:i+n]) for i in range(len(ws) - n + 1)}


def jaccard(a: set, b: set) -> float:
    if not a or not b: return 0.0
    return len(a & b) / len(a | b)


def paper_match(target_title: str, candidate_title: str) -> bool:
    nt, nc = norm_text(target_title), norm_text(candidate_title)
    if not nt or not nc: return False
    if nt == nc: return True
    if len(nt) >= 15 and nt in nc: return True
    if len(nc) >= 15 and nc in nt: return True
    return False


def theorem_match(target_body: str, candidate_body: str) -> bool:
    if not target_body or not candidate_body: return False
    t4 = ngrams(target_body, 4)
    c4 = ngrams(candidate_body, 4)
    # short body fallback: token-level Jaccard
    if len(t4) < 5:
        return jaccard(ngrams(target_body, 1), ngrams(candidate_body, 1)) > 0.5
    overlap = len(t4 & c4)
    return overlap >= 2 or (overlap >= 1 and len(t4) <= 10)


def first_rank(top10: list, predicate) -> int | None:
    for i, h in enumerate(top10, 1):
        if predicate(h):
            return i
    return None


def main():
    results = json.load(open(SEARCH))
    picks = json.load(open(PICKS))
    pick_index = {(p['paper'], p['label'] or ''): p['body'] for p in picks}

    graded: list[dict] = []
    for r in results:
        body = pick_index.get((r['paper'], r['label'] or ''), '')
        if not body:
            continue
        ts_paper = first_rank(r['ts_top10'],
            lambda h: paper_match(r['target_title'], h.get('title','')))
        m_paper = first_rank(r['matlas_top10'],
            lambda h: paper_match(r['target_title'], h.get('title','')))
        ts_thm = first_rank(r['ts_top10'],
            lambda h: paper_match(r['target_title'], h.get('title','')) and theorem_match(body, h.get('body','')))
        m_thm = first_rank(r['matlas_top10'],
            lambda h: paper_match(r['target_title'], h.get('title','')) and theorem_match(body, h.get('statement','')))
        graded.append({**r, "target_body": body[:300],
                       "ts_paper_rank": ts_paper, "matlas_paper_rank": m_paper,
                       "ts_thm_rank": ts_thm, "matlas_thm_rank": m_thm})

    os.makedirs(os.path.dirname(GRADED), exist_ok=True)
    with open(GRADED, "w") as f:
        json.dump(graded, f)
    print(f"Graded: {len(graded)} queries → {GRADED}")

    # Flat CSV
    with open(CSV_OUT, "w", newline='') as f:
        w = csv.writer(f)
        w.writerow(["paper","theorem_label","theorem_type","mode","query","target_title",
                    "ts_paper_rank","matlas_paper_rank","ts_theorem_rank","matlas_theorem_rank",
                    "ts_top1_title","matlas_top1_title"])
        for r in graded:
            w.writerow([r['paper'], r['label'], r['type'], r['mode'], r['query'], r['target_title'],
                        r['ts_paper_rank'], r['matlas_paper_rank'], r['ts_thm_rank'], r['matlas_thm_rank'],
                        (r['ts_top10'][0]['title'][:80] if r['ts_top10'] else ""),
                        (r['matlas_top10'][0]['title'][:80] if r['matlas_top10'] else "")])
    print(f"CSV → {CSV_OUT}")

    # Summary tables
    def stats(graded, mode, engine, level):
        rs = [r for r in graded if (mode is None or r['mode'] == mode)]
        n = len(rs)
        rk = [r[f'{engine}_{level}_rank'] for r in rs]
        return (n, sum(1 for x in rk if x == 1),
                   sum(1 for x in rk if x and x <= 3),
                   sum(1 for x in rk if x and x <= 5),
                   sum(1 for x in rk if x and x <= 10))

    for level_name, level in (("PAPER-level", "paper"), ("THEOREM-level", "thm")):
        print(f"\n=== {level_name} retrieval ===")
        print(f"{'Engine':10s} {'Mode':10s} {'n':>5s}     @1         @3         @5         @10")
        print("-" * 80)
        for engine in ("ts", "matlas"):
            for mode in ("precise", "vague", None):
                m_label = mode or "ALL"
                n, t1, t3, t5, t10 = stats(graded, mode, engine, level)
                if n == 0: continue
                print(f"{engine:10s} {m_label:10s} {n:>5d}    "
                      f"{t1:>3d} ({100*t1/n:>3.0f}%) "
                      f"{t3:>3d} ({100*t3/n:>3.0f}%) "
                      f"{t5:>3d} ({100*t5/n:>3.0f}%) "
                      f"{t10:>3d} ({100*t10/n:>3.0f}%)")


if __name__ == "__main__":
    main()
