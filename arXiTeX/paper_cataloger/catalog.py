import zipfile
import io
import json
from typing import Iterator, List
from pathlib import Path
from .types import Paper
from .lib.download_arxiv_metadata import download_arxiv_metadata
from .lib.citations import fetch_paper_citations

def catalog_papers(
    download_dir: Path | str,
    categories: List[str],
    batch_size: int = 100
) -> Iterator[Paper]:
    """
    Generator that yields arXiv paper metadata. Filters by categories and returns results in the
    specified batch size.

    Parameters
    ----------
    download_dir : Path | str
        Path to directory of 'arxiv.zip', the zip of the arXiv Kaggle dataset. If this directory
        doesn't include 'arxiv.zip', just downloads it there with a progress bar.
    categories : List[str]
        List of categories to filter papers by. Specify either the whole category name (i.e.
        math.AG) or just the main category (i.e. math).
    batch_size : int, optional
        Size of batch of paper metadatas to yield. Default, 100
    
    Returns
    -------
    paper_catalog : Iterator[Paper]
        Iterator of paper metadatas
    """

    if isinstance(download_dir, str):
        download_dir = Path(download_dir)

    metadata_zip = download_dir / "arxiv.zip"
    if not metadata_zip.exists():
        download_arxiv_metadata(download_dir)
        
    batch: List[Paper] = []

    def category_match(row_categories: List[str]) -> bool:
        for rc in row_categories:
            for c in categories:
                if (c == rc) or ("." not in c and rc.startswith(c + ".")):
                    return True
        
        return False

    with zipfile.ZipFile(metadata_zip, "r") as z:
        with z.open(z.namelist()[0], "r") as raw, io.TextIOWrapper(raw, encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                paper_id = row.get("id")
                row_categories = row.get("categories").split()
                
                if not category_match(row_categories):
                    continue

                paper = Paper(
                    id=paper_id,
                    title=row.get("title"),
                    license=row.get("license"),
                    authors=[" ".join(filter(None, [f, *m, l])) for (l, f, *m) in row.get("authors_parsed")],
                    link="https://arxiv.org/pdf/" + row.get("id"),
                    abstract=row.get("abstract"),
                    journal_ref=row.get("journal-ref"),
                    categories=row_categories,
                    citations=None
                )

                batch.append(paper)

                if len(batch) >= batch_size:
                    ks = fetch_paper_citations([paper.id for paper in batch])
                    for k, paper in zip(ks, batch):
                        paper.citations = k

                    yield batch
                    batch.clear()

            if len(batch) > 0:
                ks = fetch_paper_citations([paper.id for paper in batch])
                for k, paper in zip(ks, batch):
                    paper.citations = k

                yield batch
                batch.clear()