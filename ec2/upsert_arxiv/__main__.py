import arxiv
from .arxiv_papers import get_arxiv_papers
from .citations import get_paper_citations
from ..rds.connect import get_rds_connection
from ..rds.upsert import upsert_row
import feedparser
from tqdm import tqdm
import argparse
from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed

def _get_papers_count_matching_query(query: str):
    arxiv_url = f"https://export.arxiv.org/api/query?search_query={query}&start=0&max_results=1"

    arxiv_feed = feedparser.parse(arxiv_url)
    return int(arxiv_feed.feed.opensearch_totalresults)

def _upsert_arxiv_paper(paper_res: arxiv.Result):
    conn = get_rds_connection()

    paper_id = paper_res.get_short_id()

    paper_row = {
        "paper_id": paper_id,
        "title": paper_res.title,
        "authors": [author.name for author in paper_res.authors],
        "link": paper_res.entry_id,
        "last_updated": paper_res.updated.isoformat(),
        "summary": paper_res.summary,
        "journal_ref": paper_res.journal_ref,
        "primary_category": paper_res.primary_category,
        "categories": paper_res.categories,
        "citations": get_paper_citations(paper_id, paper_res)
    }

    with conn.cursor() as cur:
        upsert_row(
            cur, 
            table="paper", 
            row=paper_row,
            on_conflict={
                "with": ["paper_id"],
                "replace": list(paper_row.keys())[1:]
            }
        )

    # conn.commit()
    conn.close()

def _upsert_arxiv_batch(paper_res_batch: List[arxiv.Result], max_workers: int, pbar: tqdm):
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {
            ex.submit(_upsert_arxiv_paper, paper_res)
            for paper_res in paper_res_batch
        }

        for fut in as_completed(futs):
            pbar.update(1)

def upsert_arxiv(
    query: str,
    batch_size: int,
    max_workers: int,
    search_page_size: int = 100,
    search_delay_seconds: float = 3,
    search_max_retries: int = 3
):
    client = arxiv.Client(
        page_size=search_page_size,
        delay_seconds=search_delay_seconds,
        num_retries=search_max_retries
    )

    paper_res_batch = []

    with tqdm(total=_get_papers_count_matching_query(query)) as pbar:
        for paper_res in get_arxiv_papers(client, query):
            paper_res_batch.append(paper_res)

            if len(paper_res_batch) == batch_size:
                _upsert_arxiv_batch(paper_res_batch, max_workers=max_workers, pbar=pbar)
                paper_res_batch = []

        if len(paper_res_batch) > 0:
            _upsert_arxiv_batch(paper_res_batch, max_workers=max_workers, pbar=pbar)
            paper_res_batch = []

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--query",
        type=str,
        required=True,
        help="A valid arXiv search query"
    )

    parser.add_argument(
        "--workers",
        type=int,
        required=False,
        default=16,
        help="Number of workers to upsert each batch"
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        required=False,
        default=16,
        help="Number of papers in each batch"
    )

    args = parser.parse_args()

    upsert_arxiv(
        query=args.query,
        batch_size=args.batch_size,
        max_workers=args.workers
    )