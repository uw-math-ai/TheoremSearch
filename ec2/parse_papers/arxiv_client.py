import arxiv

def search_arxiv(
    query: str,
    page_size: int = 3
):
    client = arxiv.Client()

    search = arxiv.Search(
        query=query,
        sort_by = arxiv.SortCriterion.Relevance
    )

    page = []

    for res in client.results(search):
        page.append(res)

        if len(page) == page_size:
            yield page

            page = []

    if page:
        yield page
