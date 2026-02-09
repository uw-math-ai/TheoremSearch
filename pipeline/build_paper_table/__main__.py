import json
from tqdm import tqdm
from datetime import datetime, timezone
from typing import Optional
from tempfile import TemporaryDirectory
from argparse import ArgumentParser
from .categories import CATEGORIES
from ..printing import print_script_header
from rds.utils.connect import get_rds_connection
from rds.utils.upsert import upsert_rows
from arXiTeX.paper_cataloger.catalog import catalog_papers

def build_paper_table(
    arxiv_dir: Optional[str],
    batch_size: int
):
    """
    Builds the paper table.

    Parameters
    ----------
    arxiv_dir : Optional[str], optional
        Directory where 'arxiv.zip' from arXiv Kaggle dataset exists or will exist. Default,
        uses a temporary directory that is deleted after the script is done.
    batch_size : int, optional
        Size of batch of papers to write to table. Default, 1_000.
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

    for papers in catalog_papers(
        download_dir=arxiv_dir,
        categories=CATEGORIES,
        batch_size=batch_size
    ):
        if pbar is None:
            pbar = tqdm(
                dynamic_ncols=True,
                unit=" papers"
            )

        current_time = datetime.now(timezone.utc)

        upsert_rows(
            conn,
            table="paper",
            rows=[
                json.loads(paper.model_dump_json()) | {
                    "source": "arXiv",
                    "link": "https://arxiv.org/pdf/" + paper.id,
                    "updated_at": current_time
                } for paper in papers
            ],
            on_conflict={
                "with": ["id", "source"],
                "replace": [
                    "title", "license", "authors", 
                    "updated_at", "abstract", "journal_ref", 
                    "categories", "citations"
                ]
            }
        )

        conn.commit()

        pbar.update(len(papers))

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
        default=1_000,
        help="Size of batch of papers to write to table. Default, 1_000."
    )
    
    args = arg_parser.parse_args()

    build_paper_table(
        arxiv_dir=args.arxiv_dir or None,
        batch_size=args.batch_size
    )