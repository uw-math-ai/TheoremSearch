"""
Helpers to check if a paper high enough quality to attempt to parse.
"""

import os
import time
import requests
from typing import List

def fetch_paper_citations(arxiv_ids: List[str], retries: int = 3) -> List[int | None]:
    """
    Fetches the count of a paper's citations by its arXiv id. First, tries Semantic Scholar, then
    OpenAlex, then returns None.

    Parameters
    ----------
    arxiv_ids : List[str]
        List of papers' arXiv ids.
    retries : int, optional
        Number of retries allowed for an empty citations batch. Default 3

    Returns
    -------
    ks : List[int | None]
        The number of citations or None if none found for each paper in the same order.
    
    """

    arxiv_ids_formatted = ["ARXIV:" + arxiv_id.split("v")[0] for arxiv_id in arxiv_ids] # remove version just in case!

    try: # search Semantic Scholar
        time.sleep(1.1) # guarantee we dont make more than 1 request per second

        scholar_res = requests.post(
            f"https://api.semanticscholar.org/graph/v1/paper/batch",
            params={"fields": "citationCount"},
            json={"ids": arxiv_ids_formatted},
            headers={"x-api-key": os.getenv("SEMANTIC_SCHOLAR_API_KEY")}
        )

        if scholar_res.ok:
            scholar_data = scholar_res.json()
            
            ks = [
                paper_json.get("citationCount", None) if paper_json else None
                for paper_json in scholar_data
            ]
            
            return ks
        else:
            raise ValueError("SemanticScholar response not OK")
            
    except Exception:
        if retries > 0:
            sleep_s = round(len(arxiv_ids)**(1/retries), 2)
            print(f"Sleeping {sleep_s}s for SemanticScholar")
            
            time.sleep(sleep_s)

            return fetch_paper_citations(arxiv_ids, retries - 1)
        else:
            pass

    # try: # search OpenAlex by arXiv id
    #     alex_res = requests.get(f"https://api.openalex.org/works/doi:10.48550/arXiv.{arxiv_id}", timeout=10)

    #     if alex_res.ok:
    #         alex_data = alex_res.json()
    #         k = alex_data.get("cited_by_count")

    #         if isinstance(k, int):
    #             return k
    # except Exception:
    #     pass

    return [None for _ in arxiv_ids]


