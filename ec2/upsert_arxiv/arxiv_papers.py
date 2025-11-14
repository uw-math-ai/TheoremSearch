import arxiv
from datetime import datetime
from typing import Iterator

def get_arxiv_papers(client: arxiv.Client, query: str) -> Iterator[arxiv.Result]:
    current_year = datetime.now().year

    for year in range(current_year, 1990, -1):
        search = arxiv.Search(
            query=f"submittedDate:[{year}0101000000 TO {year}1231235959] AND {query}"
        )

        for paper_res in client.results(search):
            yield paper_res