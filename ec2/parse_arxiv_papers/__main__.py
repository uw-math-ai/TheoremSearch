from argparse import ArgumentParser
from typing import List
from ..rds.connect import get_rds_connection
from ..rds.query import build_query
from ..rds.paginate import paginate_query
from concurrent.futures import ProcessPoolExecutor, TimeoutError
from tempfile import TemporaryDirectory
from .download_paper import download_paper
from typing import Tuple
import tarfile
import os
from .extract_from_content import extract_theorem_envs
from .thmenvcapture import insert_thmenvcapture_sty, inject_thmenvcapture
import subprocess

def _parse_arxiv_paper(
    paper_id: str, 
    paper_arxiv_s3_loc: Tuple[str, int, int]
):
    with TemporaryDirectory() as paper_dir:
        src_gz_path = download_paper(paper_arxiv_s3_loc, paper_dir)
        src_dir = src_gz_path.replace(".gz", "")

        with tarfile.open(src_gz_path, "r:*") as src_tar:
            src_tar.extractall(path=src_dir)

        envs_to_titles = {
            "theorem": "Theorem",
            "lemma": "Lemma",
            "proposition": "Proposition",
            "corollary": "Corollary"
        }

        main_tex_path = None

        for src_file in os.listdir(src_dir):
            src_file_path = os.path.join(src_dir, src_file)
            if os.path.isfile(src_file_path) and src_file_path.endswith(".tex"):
                with open(src_file_path, "rb") as src_f:
                    raw = src_f.read()

                    try:
                        tex = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        tex = raw.decode("latin-1", errors="replace")

                    envs_to_titles = envs_to_titles | extract_theorem_envs(tex)

                    if "\\begin{document}" in tex:
                        main_tex_path = src_file_path

        insert_thmenvcapture_sty(envs_to_titles, src_dir)
        inject_thmenvcapture(main_tex_path)

        theorem_log_path = os.path.join(src_dir, "thm-env-capture.log")
        if os.path.exists(theorem_log_path):
            os.remove(theorem_log_path)

        print("src_dir:", os.listdir(src_dir))

        cmd = ["pdflatex", "-interaction=nonstopmode", os.path.basename(main_tex_path)]
        print("cmd:", cmd)
        subprocess.run(cmd, cwd=src_dir, check=False)

        if not os.path.exists(theorem_log_path):
            raise FileNotFoundError("thm-env-capture.log was not created")
        
        with open(theorem_log_path, "r", encoding="utf-8", errors="ignore") as f:
            print("thm-env-capture.log:", f.read())

def parse_arxiv_papers(
    # SEARCH
    paper_ids: List[str],
    # CONFIG
    batch_size: int,
    workers: int
):
    conn = get_rds_connection()

    query, params = build_query(
        base_query="""
            SELECT paper.paper_id, last_updated, bundle_tar, bytes_start, bytes_end
            FROM paper
              INNER JOIN paper_arxiv_s3_location paper_loc
                ON paper_loc.paper_id = paper.paper_id
        """,
        where_clauses=[
            {
                "if": len(paper_ids) > 0,
                "condition": "paper.paper_id LIKE ANY(%s)",
                "param": ["%" + paper_id + "%" for paper_id in paper_ids]
            }
        ]
    )

    # TODO: Find an efficient way to get the number of results returned from query

    with ProcessPoolExecutor(max_workers=workers) as ex:
        for papers in paginate_query(
            conn,
            base_sql=query,
            base_params=(*params,),
            order_by="last_updated",
            descending=True,
            page_size=batch_size
        ):
            paper_futures = []
            batch_theorem_rows = []
            
            for paper in papers:
                paper_id = paper["paper_id"]
                paper_arxiv_s3_loc = (paper["bundle_tar"], paper["bytes_start"], paper["bytes_end"])

                fut = ex.submit(_parse_arxiv_paper, paper_id, paper_arxiv_s3_loc)
                paper_futures.append((paper_id, fut))

            for paper_id, fut in paper_futures:
                theorem_rows = []

                try:
                    theorem_rows = fut.result()
                except TimeoutError:
                    print(f"[TIMEOUT] {paper_id}")
                except Exception as e:
                    print(f"[FUTURE ERROR] {paper_id}: {e!r}", flush=True)

                if theorem_rows:
                    batch_theorem_rows.extend(theorem_rows)

if __name__ == "__main__":
    arg_parser = ArgumentParser()

    arg_parser.add_argument(
        "--paper-ids",
        type=str,
        nargs="+",
        default=[],
        help="IDs of papers to parse"
    )

    arg_parser.add_argument(
        "--batch-size",
        type=int,
        required=False,
        default=32,
        help="Number of papers per batch"
    )

    arg_parser.add_argument(
        "--workers",
        type=int,
        required=False,
        default=16,
        help="Maximum number of workers"
    )

    args = arg_parser.parse_args()

    parse_arxiv_papers(
        # SEARCH
        paper_ids=args.paper_ids,

        # CONFIG
        batch_size=args.batch_size,
        workers=args.workers
    )
