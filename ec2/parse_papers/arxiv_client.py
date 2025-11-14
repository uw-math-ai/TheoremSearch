import arxiv
from typing import Iterable, List
import tqdm

ArXivBatch = List[arxiv.Result]

def fetch_arxiv_papers(
    query: str,
    start: int = 0,
    sort_by: arxiv.SortCriterion = arxiv.SortCriterion.SubmittedDate,
    page_size: int = 100,
    delay_seconds: float = 3,
    max_retries: int = 3
) -> Iterable[ArXivBatch]:
    client = arxiv.Client(
        page_size=page_size,
        delay_seconds=delay_seconds,
        num_retries=max_retries
    )

    search = arxiv.Search(
        query=query,
        sort_by=sort_by
    )

    while True:
        try:
            for paper_res in client.results(search, offset=start):
                start += 1
                yield paper_res

            break
        except Exception as e:
            start += 1

            print(f"reset @ start={start}")

if __name__ == "__main__":
    with tqdm.tqdm(total=50_000) as pbar:
        for paper_res in fetch_arxiv_papers(query="cat:math.AG", delay_seconds=0.3):
            pbar.update(1)