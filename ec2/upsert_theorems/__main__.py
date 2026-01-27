"""
Accepts a link or filepath to a parsed theorems JSON and upserts it to RDS.
"""

import gdown
from argparse import ArgumentParser
from tempfile import TemporaryDirectory
from pathlib import Path
import json
from typing import Optional
from ..rds.connect import get_rds_connection
from ..rds.upsert import upsert_row, upsert_rows
from tqdm import tqdm

THEOREM_TYPES = { "theorem", "lemma", "proposition", "corollary" }

def _upsert_theorems_from_json(
    drive_link: str,
    source: str,
    title: Optional[str] = None,
    source_link: Optional[str] = None,
    paper_id: Optional[str] = None
):
    if not title:
        title = source
    if not paper_id:
        paper_id = source.replace(" ", "-").lower()

    # TODO: Use TemporaryDirectory instead
    source_file = Path(f"DEBUG/{paper_id}.json")

    gdown.download(drive_link, str(source_file))

    source_json = json.load(source_file.open("r", errors="ignore"))
    source_link = source_link or source_json["source"]

    conn = get_rds_connection()

    with conn.cursor() as cur:
        upsert_row(
            cur,
            table="paper",
            row={
                "paper_id": paper_id,
                "source": source,
                "title": title,
                "authors": [], # TODO: Add support
                "link": source_link
            }
        )

    conn.commit()

    batch_theorems = []

    for theorem in tqdm(source_json["theorems"], dynamic_ncols=True):
        if not theorem["type"] in THEOREM_TYPES:
            continue

        if "theorem_name" not in theorem:
            raise ValueError("theorem_name not in theorem")
        elif "body" not in theorem:
            raise ValueError("body not in theorem")

        batch_theorems.append({
            "paper_id": paper_id,
            "name": theorem["theorem_name"],
            "body": theorem["body"],
            "label": theorem.get("label", None),
            "link": theorem.get("link", None) or theorem.get("url", None),
            "parsing_method": "regex"
        })

        if len(batch_theorems) == 128:
            with conn.cursor() as cur:
                upsert_rows(
                    cur,
                    table="theorem",
                    rows=batch_theorems
                )

            conn.commit()

            batch_theorems = []

    if len(batch_theorems) > 0:
        with conn.cursor() as cur:
            upsert_rows(
                cur,
                table="theorem",
                rows=batch_theorems
            )

        conn.commit()

    conn.close()

if __name__ == "__main__":
    arg_parser = ArgumentParser()

    arg_parser.add_argument(
        "--link",
        required=True,
        help="Google Drive link to JSON file"
    )

    arg_parser.add_argument(
        "--source",
        required=True,
        help="Name of source"
    )

    args = arg_parser.parse_args()

    _upsert_theorems_from_json(
        drive_link=args.link,
        source=args.source
    )