"""Stage 1: pull one recent paper per arXiv math tag and extract theorem statements.

Writes data/papers.json: 10 distinct papers (one per tag), 10 theorem-like
statements each (verbatim LaTeX, lightly cleaned). Papers are chosen distinct
across tags so a cross-listed paper is not double-counted.

Note: arXiv "recent" moves over time, so re-running produces a comparable but not
byte-identical dataset. The committed data/papers.json is the frozen corpus used
for the analysis in README.md.
"""
import os, re, io, sys, json, time, tarfile, gzip, urllib.request

OUT = os.path.join(os.path.dirname(__file__), "data", "papers.json")
CATS = ["math.AG", "math.AT", "math.NT", "math.CO", "math.PR",
        "math.DG", "math.FA", "math.LO", "math.RT", "math.AP"]
N_PER_PAPER = 10
MAX_CANDIDATES = 25
UA = {"User-Agent": "theoremsearch-latex-vs-slogan/1.0 (mailto:research@uw-math-ai)"}

THM_ENVS = ["theorem", "thm", "lemma", "lem", "proposition", "prop", "corollary", "cor",
            "conjecture", "claim", "maintheorem", "mainthm", "introthm", "thmx", "theoremintro"]
ENV_RE = re.compile(
    r"\\begin\{(" + "|".join(THM_ENVS) + r")\*?\}(\[[^\]]*\])?(.*?)\\end\{\1\*?\}",
    re.DOTALL | re.IGNORECASE)


def log(*a):
    print(*a, flush=True)


def arxiv_ids(cat, n):
    q = ("http://export.arxiv.org/api/query?search_query=cat:%s"
         "&start=0&max_results=%d&sortBy=submittedDate&sortOrder=descending" % (cat, n))
    for attempt in range(3):
        try:
            xml = urllib.request.urlopen(urllib.request.Request(q, headers=UA), timeout=30).read().decode("utf-8", "ignore")
            ids = re.findall(r"<id>https?://arxiv\.org/abs/([^<]+)</id>", xml)
            ids = [re.sub(r"v\d+$", "", i.strip()) for i in ids]
            seen, out = set(), []
            for i in ids:
                if i not in seen:
                    seen.add(i); out.append(i)
            if out:
                return out
        except Exception as e:
            log("  api retry", cat, e); time.sleep(3)
    return []


def get_source_text(arxiv_id):
    try:
        raw = urllib.request.urlopen(
            urllib.request.Request("https://arxiv.org/e-print/%s" % arxiv_id, headers=UA), timeout=45).read()
    except Exception as e:
        log("   dl fail", arxiv_id, e); return None
    texts = []
    try:
        tf = tarfile.open(fileobj=io.BytesIO(raw), mode="r:*")
        for m in tf.getmembers():
            if m.isfile() and m.name.lower().endswith(".tex"):
                try:
                    texts.append(tf.extractfile(m).read().decode("utf-8", "ignore"))
                except Exception:
                    pass
        if texts:
            return "\n".join(texts)
    except Exception:
        pass
    try:
        data = gzip.decompress(raw).decode("utf-8", "ignore")
        if "\\begin" in data or "\\documentclass" in data:
            return data
    except Exception:
        pass
    return None


def strip_comments(s):
    return re.sub(r"(?<!\\)%.*", "", s)


def clean_stmt(body):
    body = strip_comments(body)
    body = re.sub(r"\\label(\[[^\]]*\])?\{[^}]*\}", "", body)
    body = re.sub(r"\\qed\b", "", body)
    return re.sub(r"\s+", " ", body).strip()


def has_math(s):
    return ("$" in s) or ("\\(" in s) or ("\\[" in s) or ("\\begin{equation" in s) or \
           bool(re.search(r"\\[A-Za-z]+", s))


def extract_theorems(text):
    out = []
    for m in ENV_RE.finditer(text):
        body = clean_stmt(m.group(3))
        if "\\begin{proof}" in body:
            body = body.split("\\begin{proof}")[0].strip()
        if not (60 <= len(body) <= 1100) or not has_math(body):
            continue
        if body.lower().startswith("see ") or "see \\cite" in body.lower()[:40]:
            continue
        out.append({"env": m.group(1).lower(), "statement": body})
    seen, uniq = set(), []
    for t in out:
        key = t["statement"][:80]
        if key not in seen:
            seen.add(key); uniq.append(t)
    return uniq


def get_title(arxiv_id):
    try:
        xml = urllib.request.urlopen(
            urllib.request.Request("http://export.arxiv.org/api/query?id_list=%s" % arxiv_id, headers=UA),
            timeout=20).read().decode("utf-8", "ignore")
        m = re.search(r"<entry>.*?<title>(.*?)</title>", xml, re.DOTALL)
        return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    except Exception:
        return ""


def main():
    results, used = [], set()
    for cat in CATS:
        log("### category", cat)
        chosen = None
        for aid in arxiv_ids(cat, MAX_CANDIDATES):
            if aid in used:          # keep papers distinct across tags
                continue
            txt = get_source_text(aid)
            if not txt:
                continue
            thms = extract_theorems(txt)
            log("   %s -> %d theorem-like statements" % (aid, len(thms)))
            if len(thms) >= N_PER_PAPER:
                chosen = {"category": cat, "arxiv_id": aid, "title": get_title(aid),
                          "theorems": thms[:N_PER_PAPER]}
                used.add(aid)
                break
            time.sleep(1)
        if chosen:
            log("  CHOSE %s (%s)" % (chosen["arxiv_id"], chosen["title"][:60]))
            results.append(chosen)
        else:
            log("  !! no suitable paper for", cat)
        json.dump(results, open(OUT, "w"), ensure_ascii=False, indent=1)
    log("DONE. papers:", len(results), "theorems:", sum(len(p["theorems"]) for p in results))


if __name__ == "__main__":
    main()
