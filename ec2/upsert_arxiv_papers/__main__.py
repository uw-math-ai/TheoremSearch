"""
Upserts arXiv paper metadatas based on a list of categories.
"""

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
from .categories import CATEGORIES
from ..printing.scripts import print_script_header

def _get_arxiv_query_size(query: str):
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
        "citations": get_paper_citations(paper_id, paper_res),
        "source": "arXiv"
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

    conn.commit()
    conn.close()

def _upsert_arxiv_batch(paper_res_batch: List[arxiv.Result], workers: int, pbar: tqdm):
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(_upsert_arxiv_paper, paper_res)
            for paper_res in paper_res_batch
        }

        for _ in as_completed(futs):
            pbar.update(1)

def _upsert_arxiv_papers(
    categories: List[str],
    batch_size: int,
    workers: int
):
    print_script_header(
        action="Upserting paper metadata to `paper`",
        params={
            "categories?": categories,
            "batch_size": batch_size,
            "workers": workers,
        }
    )

    if not categories:
        categories = CATEGORIES

    for category_index, category in enumerate(categories):
        print(f"Querying category {category} ({category_index + 1}/{len(categories)})")
        
        query = f"cat:{category}"

        client = arxiv.Client(
            page_size=100,
            delay_seconds=3,
            num_retries=3
        )

        paper_res_batch = []

        papers_left = _get_arxiv_query_size(query)

        with tqdm(total=papers_left, dynamic_ncols=True) as pbar:
            for paper_res in get_arxiv_papers(client, query, date_partition="month"):
                paper_res_batch.append(paper_res)

                if len(paper_res_batch) == batch_size:
                    _upsert_arxiv_batch(paper_res_batch, workers=workers, pbar=pbar)
                    paper_res_batch = []

                    papers_left -= batch_size

                    if papers_left <= 0:
                        break

            if len(paper_res_batch) > 0:
                _upsert_arxiv_batch(paper_res_batch, workers=workers, pbar=pbar)
                paper_res_batch = []

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--categories",
        type=str,
        required=False,
        nargs="*",
        default=[],
        help="A list of valid categories. If empty, does all math categories"
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        required=False,
        default=16,
        help="Number of papers in each batch"
    )

    parser.add_argument(
        "--workers",
        type=int,
        required=False,
        default=4,
        help="Number of workers to upsert each batch"
    )

    args = parser.parse_args()

    _upsert_arxiv_papers(
        categories=args.categories,
        batch_size=args.batch_size,
        workers=args.workers
    )