from .arxiv_client import search_arxiv
import argparse
import shutil
import os
from ..rds.connect import get_rds_connection
import tarfile
import gzip
from .tex import find_main_tex_file, collect_imports
import regex
from .patterns import *
from .latex_parse import extract
from .citations import fetch_citations
from arxiv import Result
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from typing import Literal

TMP_DIR = "papers_tmp"

Status = Literal["upserted", "skipped", "error"]

def _parse_paper(
    paper_res: Result,
    overwrite: bool = False,
    allowed_theorem_types: set[str] = set(["theorem", "proposition", "lemma"]),
) -> Status:
    conn = get_rds_connection()

    paper_id = paper_res.get_short_id()

    try:
        tar_path = paper_res.download_source(
            dirpath=TMP_DIR, 
            filename=paper_id.replace("/", "_") + ".tar.gz"
        )
    except Exception as e:
        # print(f"Error: {e}")

        conn.rollback()
        return "error"

    tar_out = tar_path.replace(".tar.gz", "")

    def clean_up():
        conn.rollback()

        if os.path.exists(tar_out):
            shutil.rmtree(tar_out)
        if os.path.exists(tar_path):
            os.remove(tar_path)
        
    if not overwrite:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1
                    FROM paper
                    WHERE paper_id = %s
                );
            """, (paper_id,))

            res = cur.fetchone()

            if res[0]:
                # print(f"Prevented overwrite")

                clean_up()
                return "skipped"

    try:
        with tarfile.open(tar_path, "r:*") as tar:
            tar.extractall(path=tar_out)
    except:
        try:
            os.makedirs(tar_out)
            with gzip.open(tar_path, "rb") as f_in, open(os.path.join(tar_out, "main.tex"), "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        except Exception as e:
            # print(f"Error: {e}")

            clean_up()
            return "error"

    file = find_main_tex_file(tar_out)

    if file is None:
        # print(f"Error: No main .tex file found")

        clean_up()
        return "error"

    with open(file, "r+", encoding="utf-8", errors="ignore") as f:
        content = f.read()

        # remove any commented out imports
        content = regex.sub(r"(?<!\\)%.*", "", content)
        content = regex.sub(r'\\begin\{comment\}.*?\\end\{comment\}', '', content, flags=regex.DOTALL)
    
        f.seek(0)
        f.write(content)
        f.truncate()

    # places all imports in main file
    collect_imports(tar_out, file, NEWINPUT)
    collect_imports(tar_out, file, NEWUSEPACKAGE)

    try:
        theorems = extract(file)
        theorem_rows = [
            (name, body, label)
            for name, body, label in theorems
            if name.lower().split(" ")[0] in allowed_theorem_types
        ]

        if not theorem_rows:
            # print(f"Error: No theorems found")

            clean_up()
            return "error"

        paper_row = (
            paper_id,
            paper_res.title,
            [author.name for author in paper_res.authors],
            paper_res.entry_id, # link
            paper_res.updated.isoformat(),
            paper_res.summary,
            paper_res.journal_ref,
            paper_res.primary_category,
            paper_res.categories,
            fetch_citations(paper_res.entry_id, paper_res.title)
        )

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO paper (
                    paper_id, title, authors, link, last_updated, summary, journal_ref,
                    primary_category, categories, citations
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (paper_id) DO UPDATE
                SET
                    last_updated = EXCLUDED.last_updated,
                    citations = EXCLUDED.citations
            """, paper_row)

            for theorem_row in theorem_rows:
                cur.execute("""
                    INSERT INTO theorem (
                        paper_id, name, body, label
                    )
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (paper_id, name) DO UPDATE
                    SET 
                        body = EXCLUDED.body,
                        label = EXCLUDED.label;
                """, (
                    paper_id,
                    *theorem_row
                ))
        
        conn.commit()

        clean_up()
        return "upserted"

    except Exception as e:
        # print(f"Error: {e}")

        clean_up()
        return "error"

def parse_papers(
    query: str,
    overwrite: bool = False,
    limit: int = 10,
    skip: int = 0,
    allowed_theorem_types: set[str] = set(["theorem", "proposition", "lemma"]),
    max_workers: int = 8
):
    try:
        upserts = 0
        skips = 0
        errors = 0

        os.makedirs(TMP_DIR, exist_ok=True)
        with tqdm(total=limit, ncols=80) as pbar:
            for papers_res in search_arxiv(query, skip=skip):
                if upserts >= limit:
                    break
                
                with ThreadPoolExecutor(max_workers) as ex:
                    futs = {
                        ex.submit(_parse_paper, paper_res, overwrite, allowed_theorem_types)
                        for paper_res in papers_res
                    }

                    for fut in as_completed(futs):
                        status = fut.result()
                        
                        if status == "upserted":
                            upserts += 1
                            pbar.update(1)
                        elif status == "error":
                            errors += 1
                        elif status == "skipped":
                            skips += 1

                        pbar.set_postfix({"skip": skips, "err": errors})
    except KeyboardInterrupt:
        raise
    finally:    
        if os.path.exists(TMP_DIR):
            shutil.rmtree(TMP_DIR, ignore_errors=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--query",
        type=str,
        required=True,
        help="A valid arXiv search query"
    )

    parser.add_argument(
        "-o",
        "--overwrite",
        help="Whether to overwrite prexisting paper and theorem data"
    )

    parser.add_argument(
        "--limit",
        type=int,
        required=False,
        default=-1,
        help="Maximum number of papers to add (if no overwrite) or update/add (if overwrite)"
    )

    parser.add_argument(
        "--skip",
        type=int,
        required=False,
        default=0,
        help="Number of results to skip before attempting parsing"
    )

    args = parser.parse_args()

    parse_papers(
        args.query,
        args.overwrite,
        args.limit,
        args.skip
    )
