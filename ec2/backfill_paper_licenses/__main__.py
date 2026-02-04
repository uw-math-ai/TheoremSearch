from pathlib import Path
import argparse
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
    if not batch:
        return 0

    params = []
    for arxiv_id, license_value in batch:
        params.append((
            license_value,
            "arXiv",
            arxiv_id,
            f"{arxiv_id}v%",
        ))

    with conn.cursor() as cur:
        cur.execute("SET LOCAL synchronous_commit TO OFF")
        execute_batch(cur, UPDATE_SQL, params, page_size=128)

    return len(params)


def backfill_paper_licenses(
    zip_path: Path = arxiv_zip,
    commit_every: int = 10_000,
    shard_mod: int = 1,
    shard_idx: int = 0,
) -> None:
    if shard_mod <= 0:
        raise ValueError("shard_mod must be > 0")
    if not (0 <= shard_idx < shard_mod):
        raise ValueError("shard_idx must satisfy 0 <= shard_idx < shard_mod")

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
            print(f"Row-sharding: shard_idx={shard_idx} / shard_mod={shard_mod}")

            batch: list[tuple[str, str]] = []
            staged = 0

            seen_total = 0          # all lines read from the file
            shard_lines = 0         # lines that belong to this shard (tqdm should show this)
            parsed = 0              # shard lines successfully parsed as JSON
            matched = 0             # shard lines with (id, license)

            with zf.open(meta_name, "r") as raw_f, io.TextIOWrapper(raw_f, encoding="utf-8") as f:
                pbar = tqdm.tqdm(desc=f"Backfilling licenses (shard {shard_idx}/{shard_mod})", unit="lines")
                try:
                    for line in f:
                        seen_total += 1

                        # decide shard membership using the file line index
                        if (seen_total - 1) % shard_mod != shard_idx:
                            continue

                        shard_lines += 1
                        pbar.update(1)

                        line = line.strip()
                        if not line:
                            continue

                        try:
                            rec = json.loads(line)
                            parsed += 1
                        except json.JSONDecodeError:
                            continue

                        arxiv_id = rec.get("id")
                        license_value = rec.get("license")
                        if not arxiv_id or not license_value:
                            continue

                        matched += 1
                        batch.append((arxiv_id, license_value))

                        if len(batch) >= commit_every:
                            staged += _flush_batch(conn, batch)
                            conn.commit()
                            batch.clear()

                    if batch:
                        staged += _flush_batch(conn, batch)
                        conn.commit()
                        batch.clear()
                finally:
                    pbar.close()

            print(f"Done. Total lines read (all shards): {seen_total:,}.")
            print(f"Shard lines processed (tqdm count): {shard_lines:,}. Parsed: {parsed:,}. Matched: {matched:,}.")
            print(f"Executed {staged:,} update statements (batched).")

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill arXiv paper licenses from arxiv.zip using row-number sharding.")
    p.add_argument("--zip-path", type=Path, default=arxiv_zip, help="Path to arxiv.zip")
    p.add_argument("--commit-every", type=int, default=10_000, help="How many updates to stage per commit")
    p.add_argument("--shard-mod", type=int, required=True, help="Total number of shards (e.g., 20)")
    p.add_argument("--shard-idx", type=int, required=True, help="Shard index in [0, shard-mod)")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    backfill_paper_licenses(
        zip_path=args.zip_path,
        commit_every=args.commit_every,
        shard_mod=args.shard_mod,
        shard_idx=args.shard_idx,
    )