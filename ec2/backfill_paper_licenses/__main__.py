from pathlib import Path
import json
import zipfile
import tqdm
import io

from psycopg2.extras import execute_batch

from ..rds.connect import get_rds_connection

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

def _flush_batch(conn, batch: list[tuple[str, str]]) -> int:
    """
    Runs a batched UPDATE. NO commit happens in here.
    Returns number of parameter-sets executed (not rows updated).
    """
    if not batch:
        return 0

    params = []
    for arxiv_id, license_value in batch:
        # IMPORTANT: execute_batch needs one tuple per execution with 4 params
        params.append((
            license_value,
            "arXiv",
            arxiv_id,
            f"{arxiv_id}v%",
        ))

    with conn.cursor() as cur:
        # Optional but often a big speedup for backfills (less WAL fsync pressure).
        # If you crash mid-run, you just re-run; so this is usually acceptable.
        cur.execute("SET LOCAL synchronous_commit TO OFF")

        execute_batch(cur, UPDATE_SQL, params, page_size=128)

    return len(params)

def backfill_paper_licenses(zip_path: Path = arxiv_zip, commit_every: int = 128) -> None:
    conn = get_rds_connection()
    conn.autocommit = False

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            candidates = [
                n for n in zf.namelist()
                if n.lower().endswith((".json", ".jsonl"))
                and "arxiv" in n.lower()
                and "metadata" in n.lower()
            ]
            if not candidates:
                jsons = [n for n in zf.namelist() if n.lower().endswith((".json", ".jsonl"))]
                if not jsons:
                    raise RuntimeError("No .json/.jsonl file found inside arxiv.zip")
                candidates = sorted(jsons, key=lambda n: zf.getinfo(n).file_size, reverse=True)

            meta_name = candidates[0]
            print(f"Using metadata file: {meta_name}")

            batch: list[tuple[str, str]] = []
            staged = 0

            with zf.open(meta_name, "r") as raw_f, io.TextIOWrapper(raw_f, encoding="utf-8") as f:
                for line in tqdm.tqdm(f, desc="Backfilling licenses", unit="lines"):
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    arxiv_id = rec.get("id")
                    license_value = rec.get("license")
                    if not arxiv_id or not license_value:
                        continue

                    batch.append((arxiv_id, license_value))

                    if len(batch) >= commit_every:
                        staged += _flush_batch(conn, batch)  # NO commit in here
                        conn.commit()                        # commit is outside cursor context
                        batch.clear()

                if batch:
                    staged += _flush_batch(conn, batch)      # NO commit in here
                    conn.commit()                            # commit is outside cursor context
                    batch.clear()

            print(f"Done. Executed {staged:,} update statements (batched).")

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    backfill_paper_licenses()
