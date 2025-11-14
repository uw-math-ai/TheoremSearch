"""
Helpers to check if a paper high enough quality to attempt to parse.
"""

import requests
from arxiv import Result

def get_paper_citations(
    paper_id: str, 
    paper_res: Result,
) -> int | None:
    paper_id = paper_id.split("v")[0]

    try: # search OpenAlex by arXiv id
        alex_res = requests.get(f"https://api.openalex.org/works/doi:10.48550/arXiv.{paper_id}", timeout=10)

        if alex_res.ok:
            alex_data = alex_res.json()
            k = alex_data.get("cited_by_count")

            if isinstance(k, int):
                return k
    except Exception as e:
        pass

    try: # search Semantic Scholar by arXiv id
        scholar_res = requests.get(
            f"https://api.semanticscholar.org/graph/v1/paper/arXiv:{paper_id}",
            params={"fields": "citationCount"},
            timeout=10
        )

        if scholar_res.ok:
            scholar_data = scholar_res.json()
            k = scholar_data.get("citationCount")

            if isinstance(k, int):
                return k
    except Exception as e:
        pass

    try: # search Semantic Scholar by arXiv id
        scholar_res = requests.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={"query": paper_res.title, "limit": 1, "fields": "title,citationCount"},
            timeout=10
        )

        if scholar_res.ok:
            data = scholar_res.json()
            items = data.get("data") or []
            if items:
                item = items[0]
                if item.get("title", "").strip().lower() == paper_res.title.strip().lower():
                    k = item.get("citationCount")
                    if isinstance(k, int):
                        return k

    except Exception as e:
        pass 

    return None


