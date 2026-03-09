from tqdm import tqdm
from typing import Optional
from tempfile import TemporaryDirectory
from argparse import ArgumentParser
from ..printing import print_script_header
from rds.utils.connect import get_rds_connection
from rds.utils.upsert import upsert_rows
from arXiTeX import paper_catalog

def build_paper_table(
    arxiv_dir: Optional[str],
    batch_size: int
):
    """
    Builds the paper table.

    Parameters
    ----------
    arxiv_dir : Optional[str]
        Directory where 'arxiv.zip' from arXiv Kaggle dataset exists or will exist. If None, uses
        a temporary directory.
    batch_size : int, optional
        Size of batch of papers to write to table.
    """

    if arxiv_dir is None:
        with TemporaryDirectory() as temp_dir:
            build_paper_table(temp_dir, batch_size)

        return
    
    print_script_header(
        "Building the paper table",
        params={
            "arXiv dir?": arxiv_dir,
            "batch size": batch_size
        }
    )

    conn = get_rds_connection("v2")
    pbar = None

    for papers in paper_catalog(
        download_dir=arxiv_dir,
        batch_size=batch_size
    ):
        if pbar is None:
            pbar = tqdm(
                dynamic_ncols=True,
                unit=" papers"
            )

        upsert_rows(
            conn,
            table="paper",
            rows=[
                {
                    "kind": "paper",
                    "source": "arXiv",
                    "title": paper.title,
                    "authors": paper.authors,
                    "url": paper.url,
                    "external_id": paper.arxiv_id,
                    "categories": paper.categories,
                    "updated_at": paper.updated_at,
                } for paper in papers
            ],
            on_conflict={
                "with": ["source", "external_id"],
                "replace": [
                    "kind", "title", "authors", "url", "categories", "updated_at"
                ]
            }
        )

        upsert_rows(
            conn,
            table="arxiv_paper_metadata",
            rows=[
                {
                    "arxiv_id": paper.arxiv_id,
                    "journal_ref": paper.journal_ref,
                    "doi": paper.doi,
                    "license": paper.license,
                    "abstract": paper.abstract,
                    "citation_count": paper.citation_count,
                    "reference_ids": paper.reference_ids
                } for paper in papers
            ],
            on_conflict={
                "with": ["arxiv_id"],
                "replace": [
                    "journal_ref", "doi", "license", "abstract", "citation_count", "reference_ids"
                ]
            }
        )

        conn.commit()

        pbar.update(len(papers))

    if pbar is not None:
        pbar.close()

if __name__ == "__main__":
    arg_parser = ArgumentParser()

    arg_parser.add_argument(
        "-d",
        "--arxiv-dir",
        type=str,
        required=False,
        default="",
        help="Directory where 'arxiv.zip' from arXiv Kaggle dataset exists or will exist. "
             "Default, uses a temporary directory that is deleted after the script is done."
    )

    arg_parser.add_argument(
        "-b",
        "--batch-size",
        type=int,
        required=False,
        default=100,
        help="Size of batch of papers to write to table. Default, 100."
    )
    
    args = arg_parser.parse_args()

    build_paper_table(
        arxiv_dir=args.arxiv_dir or None,
        batch_size=args.batch_size
    )