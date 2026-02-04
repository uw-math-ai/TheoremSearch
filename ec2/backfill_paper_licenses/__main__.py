from pathlib import Path
import argparse
import hashlib
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

def _stable_shard(arxiv_id: str, shard_mod: int) -> int:
    """
    Deterministic shard assignment in [0, shard_mod).
    md5 is stable across runs/machines (unlike Python's built-in hash()).
    """
    digest = hashlib.md5(arxiv_id.encode("utf-8")).digest()
    # Use first 8 bytes -> int, then mod
    return int.from_bytes(digest[:8], byteorder="big", signed=False) % shard_mod


def _flush_batch(conn, batch: list[tuple[str, str]]) -> int:
    """
    Runs a batched UPDATE. NO commit happens in here.
    Returns number of parameter-sets executed (not rows updated).
    """
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
    commit_every: int = 128,
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
            print(f"Sharding: shard_idx={shard_idx} / shard_mod={shard_mod}")

            batch: list[tuple[str, str]] = []
            staged = 0
            seen = 0
            matched = 0

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

                    if _stable_shard(arxiv_id, shard_mod) != shard_idx:
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

            print(f"Done. Lines seen: {seen:,}. Records in shard: {matched:,}.")
            print(f"Executed {staged:,} update statements (batched).")

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill arXiv paper licenses from arxiv.zip using ID sharding.")
    p.add_argument("--zip-path", type=Path, default=arxiv_zip, help="Path to arxiv.zip")
    p.add_argument("--commit-every", type=int, default=128, help="How many updates to stage per commit")

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