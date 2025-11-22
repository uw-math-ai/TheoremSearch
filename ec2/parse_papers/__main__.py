import argparse
from ..rds.paginate import paginate_query
from ..rds.connect import get_rds_connection
from tqdm import tqdm
import boto3
import tempfile
import tarfile, regex, os, shutil, gzip
from .tex import find_main_tex_file, collect_imports
from .patterns import *
from .latex_parse import extract
from typing import Set, List, Dict, Tuple
from ..rds.upsert import upsert_rows
from concurrent.futures import ProcessPoolExecutor, TimeoutError
import time

ARXIV_BUCKET = "arxiv"

s3 = boto3.client("s3")

def _download_arxiv_source(paper_arxiv_s3_loc: Tuple[str, int, int], dest_dir: str) -> str:
    bundle_tar, bytes_start, bytes_end = paper_arxiv_s3_loc
    byte_range = f"bytes={bytes_start}-{bytes_end}"

    # Make filename unique per slice so you don't overwrite for same bundle
    tar_path = os.path.join(
        dest_dir,
        f"{os.path.basename(bundle_tar)}.{bytes_start}-{bytes_end}.gz"
    )

    # Use get_object with Range + RequestPayer instead of download_fileobj
    response = s3.get_object(
        Bucket=ARXIV_BUCKET,
        Key=bundle_tar,
        Range=byte_range,
        RequestPayer="requester",
    )

    body = response["Body"]

    # Stream to disk in chunks
    with open(tar_path, "wb") as f:
        for chunk in iter(lambda: body.read(8192), b""):
            f.write(chunk)

    return tar_path

def _parse_arxiv_paper(
    paper_id: str,
    paper_arxiv_s3_loc: Tuple[str],
    allowed_theorem_types: Set[str],
    verbose: bool
) -> List[Dict]:
    # print(f"[START] {paper_id}", flush=True)

    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            tar_path = _download_arxiv_source(paper_arxiv_s3_loc, tmp_dir)
            tar_out = tar_path.replace(".gz", "")

            try:
                with tarfile.open(tar_path, "r:*") as tar:
                    tar.extractall(path=tar_out)
            except Exception:
                # Fallback: sometimes arXiv gives gzipped single .tex
                os.makedirs(tar_out, exist_ok=True)
                with gzip.open(tar_path, "rb") as f_in, \
                     open(os.path.join(tar_out, "main.tex"), "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)

            file = find_main_tex_file(tar_out)
            if file is None:
                raise ValueError("No main .tex file found")

            # clean comments from main tex
            with open(file, "r+", errors="ignore") as f:
                content = f.read()
                content = regex.sub(r"(?<!\\)%.*", "", content)
                content = regex.sub(
                    r'\\begin\{comment\}.*?\\end\{comment\}',
                    '',
                    content,
                    flags=regex.DOTALL
                )
                f.seek(0)
                f.write(content)
                f.truncate()

            # Collect imports (make sure collect_imports doesn't infinite-loop!)
            collect_imports(tar_out, file, NEWINPUT)
            collect_imports(tar_out, file, NEWUSEPACKAGE)

            # Extract theorems
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

            # print(f"[DONE]  {paper_id}", flush=True)

            return theorem_rows

        except Exception as e:
            if verbose:
                print(f"[ERROR] {paper_id}: {e!r}", flush=True)
            pass

        return []


def parse_arxiv_papers(
    min_citations: int,
    paper_ids: List[str],
    in_journal: bool,
    overwrite: bool,
    batch_size: int,
    batch_skip: int,
    max_workers: int,
    per_paper_timeout: int,
    unparsable_paper_ids: Set[str],
    verbose: bool,
    allowed_theorem_types: Set[str] = set(["theorem", "proposition", "lemma", "corollary"]),
):
    conn = get_rds_connection()

    base_sql = """
        SELECT paper.paper_id, last_updated, bundle_tar, bytes_start, bytes_end
        FROM paper
        INNER JOIN paper_arxiv_s3_location paper_loc
            ON paper_loc.paper_id = paper.paper_id
    """
    count_sql = """
        SELECT COUNT(*)
        FROM paper
        INNER JOIN paper_arxiv_s3_location paper_loc
            ON paper_loc.paper_id = paper.paper_id
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

    if paper_ids:
        where_conditions.append("paper.paper_id LIKE ANY(%s)")
        base_params.append(['%' + paper_id + '%' for paper_id in paper_ids])

    if min_citations >= 0:
        where_conditions.append("citations >= %s")
        base_params.append(min_citations)

    if in_journal:
        where_conditions.append("journal_ref IS NOT NULL")

    if where_conditions:
        base_sql += " WHERE " + " AND ".join(where_conditions)
        count_sql += " WHERE " + " AND ".join(where_conditions)

    with conn.cursor() as search_cur:
        search_cur.execute(count_sql, (*base_params,))
        n_results = search_cur.fetchone()[0]

    n_errors = 0
    n_successes = 0

    with ProcessPoolExecutor(max_workers=max_workers) as ex, tqdm(total=n_results) as pbar:
        for papers in paginate_query(
            conn,
            base_sql=base_sql,
            base_params=(*base_params,),
            order_by="last_updated",
            descending=True,
            page_size=batch_size
        ):
            futures = []
            paper_ids = []
            batch_theorem_rows = []
            
            if batch_skip > 0:
                pbar.update(len(papers))
                n_errors += len(papers)
                batch_skip -= 1

                continue

            for paper in papers:
                paper_id = paper["paper_id"]

                if paper_id in unparsable_paper_ids:
                    n_errors += 1

                    continue

                paper_arxiv_s3_loc = (paper["bundle_tar"], paper["bytes_start"], paper["bytes_end"])
                
                fut = ex.submit(_parse_arxiv_paper, paper_id, paper_arxiv_s3_loc, allowed_theorem_types, verbose)
                futures.append(fut)
                paper_ids.append(paper_id)

            for paper_id, fut in zip(paper_ids, futures):
                try:
                    theorem_rows = fut.result(timeout=per_paper_timeout)
                except TimeoutError:
                    if verbose:
                        print(f"[TIMEOUT] {paper_id} (> {per_paper_timeout}s)", flush=True)
                    theorem_rows = []

                    unparsable_paper_ids.add(paper_id)
                except Exception as e:
                    if verbose:
                        print(f"[FUTURE ERROR] {paper_id}: {e!r}", flush=True)
                    theorem_rows = []

                    unparsable_paper_ids.add(paper_id)

                if theorem_rows:
                    n_successes += 1
                    batch_theorem_rows.extend(theorem_rows)
                else:
                    unparsable_paper_ids.add(paper_id)

                    if verbose:
                        print(f"[ERROR] {paper_id}: No theorems found", flush=True)

                    n_errors += 1

                pbar.update(1)
                pbar.set_postfix({
                    "err": f"{(100.0 * n_errors / (n_errors + n_successes)):.2f}%"
                })

            pbar.set_postfix({
                "err": f"{(100.0 * n_errors / (n_errors + n_successes)):.2f}%"
            })

            with conn.cursor() as cur:
                if batch_theorem_rows:
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
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--min-citations",
        type=int,
        required=False,
        default=-1,
        help="The minimum citations a paper must have to be parsed. If negative (default), all papers are parsed"
    )

    parser.add_argument(
        "--paper-ids", 
        nargs="+",
        type=str,
        required=False,
        default=[],
        help="List of paper IDs which get parsed"
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
        "--batch-skip",
        type=int,
        required=False,
        default=0,
        help="Number of batches to skip in parsing"
    )

    parser.add_argument(
        "--workers",
        type=int,
        required=False,
        default=16,
        help="Number of concurrent workers to parse each batch (processes)"
    )

    parser.add_argument(
        "--per-paper-timeout",
        type=int,
        required=False,
        default=30,
        help="Maximum seconds allowed per paper parse before timing out"
    )

    parser.add_argument(
        "--max-retries",
        type=int,
        required=False,
        default=64,
        help="Maximum retries"
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Whether to print errors or not"
    )

    args = parser.parse_args()
    retries = 0

    unparsable_paper_ids = set()

    while retries < args.max_retries:
        try:
            parse_arxiv_papers(
                min_citations=args.min_citations,
                paper_ids=args.paper_ids,
                in_journal=args.in_journal,
                overwrite=args.overwrite,
                batch_size=args.batch_size,
                batch_skip=args.batch_skip,
                max_workers=args.workers,
                per_paper_timeout=args.per_paper_timeout,
                unparsable_paper_ids=unparsable_paper_ids,
                verbose=args.verbose
            )

        except KeyboardInterrupt:
            break

        except Exception as e:
            print(f"[RESTART] {e}")

            retries += 1

            time.sleep(retries * 30 + 1)

