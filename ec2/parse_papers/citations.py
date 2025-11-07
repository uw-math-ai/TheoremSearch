import requests
import re

ARXIV_ID_RE = re.compile(
    r'(?:arxiv\.org/(?:abs|pdf)/)?((?:\d{4}\.\d{4,5}|[a-z\-]+/\d{7}))',
    re.IGNORECASE
)

def fetch_citations(paper_url: str, title: str) -> int | None:
    """
    Returns citation count if found, else None.
    Tries the following sources in order:
      1) OpenAlex by arXiv id
      2) Semantic Scholar by arXiv id
      3) Semantic Scholar by title
    """
    arx_id = None
    if paper_url:
        m = ARXIV_ID_RE.search(paper_url)
        if m:
            arx_id = m.group(1)
    # OpenAlex by arXiv id
    if arx_id:
        try:
            r = requests.get(f"https://api.openalex.org/works/arXiv:{arx_id}", timeout=10)
            if r.ok:
                data = r.json()
                c = data.get("cited_by_count")
                if isinstance(c, int):
                    return c
        except Exception:
            pass
    # Semantic Scholar by arXiv id
    if arx_id:
        try:
            r = requests.get(
                f"https://api.semanticscholar.org/graph/v1/paper/arXiv:{arx_id}",
                params={"fields": "citationCount"},
                timeout=10
            )
            if r.ok:
                j = r.json()
                c = j.get("citationCount")
                if isinstance(c, int):
                    return c
        except Exception:
            pass
    # Fallback: Semantic Scholar by title
    if title:
        try:
            r = requests.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params={"query": title, "limit": 1, "fields": "title,citationCount"},
                timeout=10
            )
            if r.ok:
                j = r.json()
                if j.get("data"):
                    c = j["data"][0].get("citationCount")
                    if isinstance(c, int):
                        return c
        except Exception:
            pass

    return None
