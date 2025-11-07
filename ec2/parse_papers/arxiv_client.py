import arxiv

def search_arxiv(
    query: str,
    page_size: int = 3
):
    client = arxiv.Client(page_size=99)

    search = arxiv.Search(
        query=query,
        sort_by=arxiv.SortCriterion.Relevance,
        max_results=None
    )

    page = []

    for res in client.results(search):
        page.append(res)

        if len(page) == page_size:
            yield page

            page = []

    if page:
        yield page
