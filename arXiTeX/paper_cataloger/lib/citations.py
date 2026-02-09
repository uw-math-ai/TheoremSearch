"""
Helpers to check if a paper high enough quality to attempt to parse.
"""

import requests

def fetch_paper_citations(arxiv_id: str) -> int | None:
    """
    Fetches the count of a paper's citations by its arXiv id. First, tries Semantic Scholar, then
    OpenAlex, then returns None.

    Parameters
    ----------
    arxiv_id : str
        A paper's arXiv id.

    Returns
    -------
    k : int | None
        The number of citations or None if none found.
    
    """

    arxiv_id = arxiv_id.split("v")[0] # remove version just in case!

    try: # search Semantic Scholar 
        scholar_res = requests.get(
            f"https://api.semanticscholar.org/graph/v1/paper/ARXIV:{arxiv_id}",
            params={"fields": "citationCount"},
            timeout=10
        )

        if scholar_res.ok:
            scholar_data = scholar_res.json()
            k = scholar_data.get("citationCount")

            if isinstance(k, int):
                return k
            
    except Exception:
        pass

    try: # search OpenAlex by arXiv id
        alex_res = requests.get(f"https://api.openalex.org/works/doi:10.48550/arXiv.{arxiv_id}", timeout=10)

        if alex_res.ok:
            alex_data = alex_res.json()
            k = alex_data.get("cited_by_count")

            if isinstance(k, int):
                return k
    except Exception:
        pass

    return None


