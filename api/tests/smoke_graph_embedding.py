"""Smoke-test /graph/embedding over HTTP against a running API.

Checks every filter the website sends: that results come back, that each
filter is actually honored, that a statement never appears twice, and how
long each query takes. Read-only — it only issues GETs to /graph/embedding.

Usage
-----
    # against a local API (see api/README.md "Running locally")
    python api/tests/smoke_graph_embedding.py

    # against another deployment
    python api/tests/smoke_graph_embedding.py --base-url https://api.theoremsearch.com

    # fail if any query is slower than 5s (e.g. in CI)
    python api/tests/smoke_graph_embedding.py --max-seconds 5

Exits non-zero if any case fails a check, returns no results, or exceeds
--max-seconds. Run it twice: the first run is cold (the HNSW index and the
rows it touches are read from storage), the second shows warm latency.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# (label, query params) — mirrors what theorem-search-app sends.
CASES: list[tuple[str, list[tuple[str, str]]]] = [
    ("no filters",            []),
    ("sources=arXiv",         [("sources", "arXiv")]),
    ("sources=ProofWiki",     [("sources", "ProofWiki")]),
    ("sources=Stacks",        [("sources", "Stacks Project")]),
    ("sources=HoTT Book",     [("sources", "HoTT Book")]),
    ("multi-source",          [("sources", "arXiv"), ("sources", "Lean Repo")]),
    ("formality=formal",      [("formality", "formal")]),
    ("formality=informal",    [("formality", "informal")]),
    ("website default types", [("types", t) for t in ("theorem", "lemma", "proposition", "corollary")]),
    ("types=lemma",           [("types", "lemma")]),
    ("category=math.NT",      [("categories", "math.NT")]),
    ("category=math.CT",      [("categories", "math.CT")]),   # rare category: recall check
    ("multi-category",        [("categories", "math.AG"), ("categories", "math.NT")]),
    ("year range",            [("year_min", "2023"), ("year_max", "2024")]),
    ("in_journal=true",       [("in_journal", "true")]),
    ("in_journal=false",      [("in_journal", "false")]),
    ("citation range",        [("min_citations", "100"), ("citation_max", "1000"),
                               ("include_unknown_citations", "false")]),
    ("author",                [("authors", "Terence Tao")]),
    ("paper_filter by id",    [("paper_filter", "2301.00006")]),  # a real arXiv paper with statements
    ("paper_filter by title", [("paper_filter", "Hilbert stability")]),
    ("minimal mode",          [("mode", "minimal")]),
]

QUERY = "compact operator on a Hilbert space has discrete spectrum"
N_RESULTS = 10
# Cases where returning fewer than n_results is legitimate (few such papers).
MAY_BE_SHORT = {"paper_filter by id", "paper_filter by title", "sources=HoTT Book"}


def fetch(base_url: str, params: list[tuple[str, str]], timeout: float) -> dict:
    url = f"{base_url.rstrip('/')}/graph/embedding?" + urllib.parse.urlencode(
        [("query", QUERY), ("n_results", str(N_RESULTS))] + params
    )
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def check(label: str, params: list[tuple[str, str]], results: list[dict]) -> list[str]:
    """Filters the response must honor. Missing optional fields are skipped:
    minimal mode omits them by design."""
    sent: dict[str, list[str]] = {}
    for k, v in params:
        sent.setdefault(k, []).append(v)
    problems = []

    ids = [r["statement_id"] for r in results]
    if len(ids) != len(set(ids)):
        problems.append("duplicate statements")
    if not results:
        problems.append("no results")
    elif len(results) < N_RESULTS and label not in MAY_BE_SHORT:
        problems.append(f"only {len(results)}/{N_RESULTS} results")

    def every(field, ok) -> bool:
        return all(ok(r[field]) for r in results if r.get(field) is not None)

    if "sources" in sent and not every("source", lambda v: v in sent["sources"]):
        problems.append("source leak")
    if "formality" in sent and not every("formality", lambda v: v == sent["formality"][0]):
        problems.append("formality leak")
    if "types" in sent and not every("kind", lambda v: v in sent["types"]):
        problems.append("kind leak")
    if "categories" in sent and not every("categories", lambda v: v and v[0] in sent["categories"]):
        problems.append("category leak")
    if "year_min" in sent and not every("year", lambda v: v >= int(sent["year_min"][0])):
        problems.append("year_min leak")
    if "year_max" in sent and not every("year", lambda v: v <= int(sent["year_max"][0])):
        problems.append("year_max leak")
    if sent.get("in_journal") == ["true"] and not every("journal_ref", lambda v: bool(v)):
        problems.append("in_journal leak")
    if "min_citations" in sent and not every("citation_count", lambda v: v >= int(sent["min_citations"][0])):
        problems.append("min_citations leak")
    if "citation_max" in sent and not every("citation_count", lambda v: v <= int(sent["citation_max"][0])):
        problems.append("citation_max leak")
    if "authors" in sent and not every(
        "authors", lambda v: any(sent["authors"][0].lower() in a.lower() for a in v)
    ):
        problems.append("author leak")
    if sent.get("mode") == ["minimal"] and any(r.get("name") for r in results):
        problems.append("minimal mode returned full fields")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8123")
    parser.add_argument("--timeout", type=float, default=120.0, help="Per-request timeout. Default: 120s.")
    parser.add_argument("--max-seconds", type=float, default=None,
                        help="Fail a case that takes longer than this.")
    args = parser.parse_args()

    print(f"{args.base_url}  query={QUERY!r}  n_results={N_RESULTS}\n")
    print(f"{'case':24s} {'n':>3s} {'secs':>6s}  checks")
    failures = 0
    for label, params in CASES:
        t = time.time()
        try:
            results = fetch(args.base_url, params, args.timeout).get("results", [])
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            detail = getattr(e, "reason", e)
            print(f"{label:24s} {'-':>3s} {time.time() - t:6.1f}  REQUEST FAILED: {detail}")
            failures += 1
            continue
        elapsed = time.time() - t
        problems = check(label, params, results)
        if args.max_seconds is not None and elapsed > args.max_seconds:
            problems.append(f"slower than {args.max_seconds}s")
        failures += bool(problems)
        print(f"{label:24s} {len(results):>3d} {elapsed:6.1f}  {'; '.join(problems) if problems else 'ok'}")

    print(f"\n{len(CASES) - failures}/{len(CASES)} cases passed.")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
