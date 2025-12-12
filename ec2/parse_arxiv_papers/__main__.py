from argparse import ArgumentParser
from ..rds.connect import get_rds_connection
from ..rds.query import build_query
from ..rds.paginate import paginate_query
from ..rds.upsert import upsert_rows
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from tempfile import TemporaryDirectory
from .download_paper import download_paper, extract_arxiv_src
from typing import Tuple, List, Optional
import os
from .extract_from_content import extract_theorem_envs
from .thmenvcapture import insert_thmenvcapture_sty, inject_thmenvcapture
from .pdflatex import run_pdflatex, generate_dummy_biblatex
from .main_tex import get_main_tex_path
from .re_patterns import LABEL_RE
from tqdm import tqdm

def _parse_arxiv_paper(
    paper_id: str,
    paper_arxiv_s3_loc: Tuple[str, int, int],
    paper_dir: Optional[str] = None
):
    if not paper_dir:
        with TemporaryDirectory() as temp_paper_dir:
            _parse_arxiv_paper(paper_id, paper_arxiv_s3_loc, paper_dir=temp_paper_dir)
    else:
        os.makedirs(paper_dir, exist_ok=True)

        src_gz_path = download_paper(paper_arxiv_s3_loc, paper_dir)
        src_dir = src_gz_path.replace(".gz", "")

        extract_arxiv_src(src_gz_path, src_dir)

        envs_to_titles = {
            "theorem": "Theorem",
            "lemma": "Lemma",
            "proposition": "Proposition",
            "corollary": "Corollary"
        }

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

        main_tex_path = get_main_tex_path(src_dir)
        main_tex_name = os.path.basename(main_tex_path)

        insert_thmenvcapture_sty(envs_to_titles, src_dir)
        inject_thmenvcapture(main_tex_path)

        generate_dummy_biblatex(src_dir)

        theorem_log_path = os.path.join(src_dir, "thm-env-capture.log")
        if os.path.exists(theorem_log_path):
            os.remove(theorem_log_path)

        run_pdflatex(main_tex_name, cwd=src_dir)

        if not os.path.exists(theorem_log_path):
            raise FileNotFoundError("thm-env-capture.log was not created")
        
        theorems = []
        
        with open(theorem_log_path, "r", encoding="utf-8", errors="ignore") as f:
            curr_theorem = {}

            for line in f.readlines():
                line = line.strip()

                if line == "BEGIN_ENV":
                    curr_theorem = {
                        "paper_id": paper_id,
                        "label": None
                    }
                elif line.startswith("name:"):
                    curr_theorem["name"] = line.split("name:", 1)[1].strip()
                elif line.startswith("label:"):
                    curr_theorem["label"] = line.split("label:", 1)[1].strip()
                elif line.startswith("body:"):
                    curr_theorem["body"] = LABEL_RE.sub("", line.split("body:", 1)[1].strip())
                elif line == "END_ENV" and curr_theorem:
                    theorems.append(curr_theorem)

        return theorems

def parse_arxiv_papers(
    # SEARCH
    paper_ids: List[str],
    overwrite: bool,
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
            },
            {
                "if": not overwrite,
                "condition": """
                    NOT EXISTS (
                        SELECT 1
                        FROM theorem
                        WHERE theorem.paper_id = paper.paper_id
                    )
                """
            }
        ]
    )

    count_query = f"""
        SELECT COUNT(*)
        FROM ({query}) AS q
    """

    with conn.cursor() as count_cur:
        count_cur.execute(count_query, (*params,))
        count = count_cur.fetchone()[0]

    parse_attempts = 0
    parse_successes = 0

    with ThreadPoolExecutor(max_workers=workers) as ex, tqdm(total=count) as pbar:
        for papers in paginate_query(
            conn,
            base_sql=query,
            base_params=(*params,),
            order_by="last_updated",
            descending=True,
            page_size=batch_size
        ):
            paper_ids = []
            futs = []
            batch_theorem_rows = []
            
            for paper in papers:
                parse_attempts += 1

                paper_id = paper["paper_id"]
                paper_arxiv_s3_loc = (paper["bundle_tar"], paper["bytes_start"], paper["bytes_end"])

                fut = ex.submit(_parse_arxiv_paper, paper_id, paper_arxiv_s3_loc)
                
                paper_ids.append(paper_id)
                futs.append(fut)

            for paper_id, fut in zip(paper_ids, futs):
                theorem_rows = []

                try:
                    theorem_rows = fut.result()
                except TimeoutError:
                    print(f"[TIMEOUT] {paper_id}")
                except Exception as e:
                    print(f"[FUTURE ERROR] {paper_id}: {repr(e)[:100]}{'…' if len(repr(e)) > 100 else ''}")

                if theorem_rows:
                    batch_theorem_rows.extend(theorem_rows)
                    parse_successes += 1

                pbar.update(1)
                pbar.set_postfix({
                    "parse_rate": f"{(100.0 * parse_successes / parse_attempts):.2f}%"
                })

            if batch_theorem_rows:
                with conn.cursor() as cur:
                    cur.execute("""
                        DELETE FROM theorem
                        WHERE paper_id = ANY(%s)
                    """, ([row["paper_id"] for row in batch_theorem_rows],))

                    upsert_rows(
                        cur,
                        table="theorem",
                        rows=batch_theorem_rows,
                        on_conflict={
                            "with": ["paper_id", "name"],
                            "replace": ["body", "label"]
                        }
                    )

                conn.commit()
                
    conn.close()

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
        "-o", "--overwrite",
        action="store_true",
        help="Whether to overwrite parsed papers"
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
        overwrite=args.overwrite,

        # CONFIG
        batch_size=args.batch_size,
        workers=args.workers
    )
