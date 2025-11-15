import argparse
from ..rds.paginate import paginate_query
from ..rds.connect import get_rds_connection
from tqdm import tqdm
import arxiv
import tempfile
import tarfile, regex, os, shutil, gzip
from .tex import find_main_tex_file, collect_imports
from .patterns import *
from .latex_parse import extract
from typing import Set
from ..rds.upsert import upsert_rows
from concurrent.futures import ThreadPoolExecutor, as_completed

def _parse_arxiv_paper(
    client: arxiv.Client, 
    paper_id: str,
    allowed_theorem_types: Set[str]
) -> bool:
    success = False

    conn = get_rds_connection()

    search = arxiv.Search(id_list=[paper_id], max_results=1)
    paper_res = client.results(search).__next__()

    if not paper_res:
        conn.close()

        return success

    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            tar_path = paper_res.download_source(
                dirpath=tmp_dir,
                filename=paper_id.replace("/", "_") + ".tar.gz"
            )
            tar_out = tar_path.replace(".tar.gz", "")

            try:
                with tarfile.open(tar_path, "r:*") as tar:
                    tar.extractall(path=tar_out)
            except:
                os.makedirs(tar_out)

                with gzip.open(tar_path, "rb") as f_in, open(os.path.join(tar_out, "main.tex"), "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)

            file = find_main_tex_file(tar_out)

            if file is None:
                raise ValueError("No main .tex file found")
            
            with open(file, "r+", errors="ignore", ) as f:
                content = f.read()

                # remove any commented out imports
                content = regex.sub(r"(?<!\\)%.*", "", content)
                content = regex.sub(r'\\begin\{comment\}.*?\\end\{comment\}', '', content, flags=regex.DOTALL)

                f.seek(0)
                f.write(content)
                f.truncate()

            collect_imports(tar_out, file, NEWINPUT)
            collect_imports(tar_out, file, NEWUSEPACKAGE)

            theorems = extract(file)
            theorem_rows = [
                {
                    "paper_id": paper_id,
                    "name": name,
                    "body": body,
                    "label": label
                }
                for name, body, label in theorems
                if name.lower().split(" ")[0] in allowed_theorem_types
            ]

            with conn.cursor() as cur:
                upsert_rows(
                    cur,
                    table="theorem",
                    rows=theorem_rows,
                    on_conflict={
                        "with": ["paper_id", "name"],
                        "replace": ["body", "label"]
                    }
                )

            conn.commit()
            
            success = True
        except Exception as e:
            pass
        finally:
            conn.close()

    return success

def parse_arxiv_papers(
    min_citations: int,
    in_journal: bool,
    overwrite: bool,
    batch_size: int,
    max_workers: int,
    allowed_theorem_types: Set[str] = set(["theorem", "proposition", "lemma", "corollary"])
):
    search_conn = get_rds_connection()

    base_sql = f"""
        SELECT paper_id, last_updated
        FROM paper
    """
    count_sql = """
        SELECT COUNT(*)
        FROM paper
    """

    where_conditions = ["link LIKE %s"]
    base_params = ["%arxiv%"]

    if not overwrite:
        where_conditions.append("""
            NOT EXISTS (
                SELECT 1
                FROM theorem
                WHERE theorem.paper_id = paper.paper_id
            )
        """)

    if min_citations >= 0:
        where_conditions.append("citations >= %s")
        base_params.append(min_citations)

    if in_journal:
        where_conditions.append("journal_ref IS NOT NULL")

    if where_conditions:
        base_sql += " WHERE " + " AND ".join(where_conditions)
        count_sql += " WHERE " + " AND ".join(where_conditions)

    with search_conn.cursor() as search_cur:
        search_cur.execute(count_sql, (*base_params,))
        n_results = search_cur.fetchone()[0]

    client = arxiv.Client()

    n_errors = 0
    n_successes = 0

    with tqdm(total=n_results) as pbar:
        for papers in paginate_query(
            search_conn,
            base_sql=base_sql,
            base_params=(*base_params,),
            order_by="last_updated",
            descending=True,
            page_size=batch_size
        ):
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futs = {
                    ex.submit(_parse_arxiv_paper, client, paper["paper_id"], allowed_theorem_types)
                    for paper in papers
                }

                for fut in as_completed(futs):
                    success = fut.result()

                    if success:
                        n_successes += 1
                    else:
                        n_errors += 1

                    pbar.update(1)
                    pbar.set_postfix({
                        "err": f"{(100.0 * n_errors / (n_errors + n_successes)):.2f}%"
                    })

    search_conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--min-citations",
        type=int,
        required=False,
        default=-1,
        help="The minimum citations a paper must have to be parsed. If negative (default), all papers are parsed"
    )

    parser.add_argument(
        "--in-journal",
        action="store_true",
        help="Whether to only parse papers with a journal reference"
    )

    parser.add_argument(
        "-o",
        "--overwrite",
        action="store_true",
        help="Whether to only parse papers without any associated parsed theorems"
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        required=False,
        default=64,
        help="Number of papers per batch"
    )

    parser.add_argument(
        "--max-workers",
        type=int,
        required=False,
        default=16,
        help="Number of concurrent workers to parse each batch"
    )

    args = parser.parse_args()

    parse_arxiv_papers(
        min_citations=args.min_citations,
        in_journal=args.in_journal,
        overwrite=args.overwrite,
        batch_size=args.batch_size,
        max_workers=args.max_workers
    )