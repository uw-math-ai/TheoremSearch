from pathlib import Path
import json
import zipfile
import tqdm
import io
from ..rds.connect import get_rds_connection
from argparse import ArgumentParser

arxiv_zip = Path("arxiv.zip")

UPDATE_SQL = """
UPDATE paper AS p
SET license = %s
WHERE p.source = %s
  AND (
        p.paper_id = %s
        OR p.paper_id LIKE %s
      )
"""

def _update(conn, batch):

    if not batch:
        return
    
    params = []
    for paper_id, license in batch:
        params.append((
            license,
            "arXiv",
            paper_id,
            f"{paper_id}v%"
        ))

    with conn.cursor() as cur:
        cur.executemany(UPDATE_SQL, params)

    conn.commit()

def backfill_paper_licenses(batch_size: int):
    conn = get_rds_connection()

    batch = []

    with zipfile.ZipFile(arxiv_zip, "r") as zf:
        with zf.open(zf.namelist()[0], "r") as raw_f, io.TextIOWrapper(raw_f, encoding="utf-8") as f:
            total_lines = 3_000_000

            # print("Counting total number of lines:")

            # for _ in f:
            #     total_lines += 1
                
            #     if total_lines % 10_000 == 0:
            #         print(" >", total_lines)

            with tqdm.tqdm(
                total=total_lines, 
                dynamic_ncols=True, 
                unit="lines"
            ) as pbar:
                for line in f:
                    row = json.loads(line)

                    paper_id = row.get("id")
                    license = row.get("license")

                    if not paper_id or not license:
                        continue
                
                    batch.append((paper_id, license))

                    if len(batch) >= batch_size:
                        _update(conn, batch)
                        pbar.update(len(batch))
                        batch.clear()

                if len(batch) > 0:
                        _update(conn, batch)
                        pbar.update(len(batch))
                        batch.clear()

if __name__ == "__main__":
    arg_parser = ArgumentParser()

    arg_parser.add_argument("--batch-size", type=int, required=False, default=4)

    args = arg_parser.parse_args()

    backfill_paper_licenses(batch_size=args.batch_size)