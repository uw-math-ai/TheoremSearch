from pathlib import Path
import json
import zipfile
import tqdm
import io

from psycopg2.extras import execute_values

from ..rds.connect import get_rds_connection

arxiv_zip = Path("arxiv.zip")

UPDATE_SQL = """
UPDATE paper AS p
SET license = v.license
FROM (VALUES %s) AS v(arxiv_id, license)
WHERE p.source = 'arXiv'
  AND (
        p.paper_id = v.arxiv_id
        OR p.paper_id LIKE (v.arxiv_id || 'v%%')
      )
"""

def _flush_batch(conn, batch: list[tuple[str, str]]) -> None:
    """Runs one batched UPDATE. No commit happens in here."""
    if not batch:
        return
    with conn.cursor() as cur:
        execute_values(cur, UPDATE_SQL, batch, page_size=5_000)

def backfill_paper_licenses(zip_path: Path = arxiv_zip, commit_every: int = 10_000) -> None:
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
            seen = 0
            staged = 0

            with zf.open(meta_name, "r") as raw_f, io.TextIOWrapper(raw_f, encoding="utf-8") as f:
                for line in tqdm.tqdm(f, desc="Backfilling licenses", unit="lines"):
                    seen += 1
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
                    staged += 1

                    if len(batch) >= commit_every:
                        _flush_batch(conn, batch)   # NO commit inside cursor
                        conn.commit()               # commit is outside cursor context
                        batch.clear()

                # final flush
                if batch:
                    _flush_batch(conn, batch)       # NO commit inside cursor
                    conn.commit()                   # commit is outside cursor context
                    batch.clear()

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    backfill_paper_licenses()