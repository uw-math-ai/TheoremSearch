"""
Helpers to retrieve (relevant) arXiv paper metadata.
"""

import arxiv

def get_paper_metadata(paper_id: str):
    result = next(arxiv.Client().results(arxiv.Search(id_list=[paper_id])))

    return {
        "title": result.title,
        "authors": [author.name for author in result.authors],
        "link": result.entry_id,
        "last_updated": result.updated.isoformat(),
        "summary": result.summary,
        "journal_ref": result.journal_ref,
        "primary_category": result.primary_category,
        "categories": result.categories
    }