from pathlib import Path
import json
import zipfile
import tqdm

from ..rds.connect import get_rds_connection

arxiv_zip = Path("arxiv.zip")

def backfill_paper_licenses(zip_path: Path = arxiv_zip, commit_every: int = 5000) -> None:
    conn = get_rds_connection()

    with zipfile.ZipFile(zip_path, "r") as zf:
        # Kaggle arXiv snapshot typically contains one large JSONL metadata file
        candidates = [
            n for n in zf.namelist()
            if n.lower().endswith((".json", ".jsonl"))
            and "arxiv" in n.lower()
            and "metadata" in n.lower()
        ]
        if not candidates:
            # fallback: take the largest json/jsonl in the zip
            jsons = [n for n in zf.namelist() if n.lower().endswith((".json", ".jsonl"))]
            if not jsons:
                raise RuntimeError("No .json/.jsonl file found inside arxiv.zip")
            candidates = sorted(jsons, key=lambda n: zf.getinfo(n).file_size, reverse=True)

        meta_name = candidates[0]
        print(f"Using metadata file: {meta_name}")

        updated = 0
        processed = 0

        with zf.open(meta_name, "r") as f, conn.cursor() as cur:
            for raw in tqdm.tqdm(f, desc="Backfilling licenses", unit="lines"):
                processed += 1
                raw = raw.strip()
                if not raw:
                    continue

                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                arxiv_id = rec.get("id")
                license_value = rec.get("license")  # Kaggle field

                if not arxiv_id or not license_value:
                    continue

                cur.execute(
                    """
                    UPDATE paper
                    SET license = %s
                    WHERE paper_id LIKE %s
                    """,
                    (license_value, f"{arxiv_id}%"),
                )
                updated += cur.rowcount

                if processed % commit_every == 0:
                    conn.commit()

            conn.commit()


if __name__ == "__main__":
    backfill_paper_licenses()