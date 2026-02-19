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
    folder_link: str,
    source: str,
    source_link: str
):
    source_id = source.lower().replace(" ", "-")

    # TODO: Use TemporaryDirectory instead
    source_folder = Path(f"DEBUG/{source_id}")

    # gdown.download_folder(url=folder_link, output=str(source_folder), remaining_ok=True)

    # return

    conn = get_rds_connection()

    for source_file in source_folder.iterdir():
        source_json = json.load(source_file.open("r", errors="ignore"))

        title = source_json["original_path"] \
            .replace(".tex", "") \
            .replace("ch", "Chapter ") \
            .replace("app", "Appendix ")
        
        title_segments = title.split("-")
        name_start = next(
            i + 1 for i in range(len(title_segments)-1, -1, -1)
            if title_segments[i] and title_segments[i][0].isdigit()
        )
        title = ".".join(title_segments[:name_start]) + " " + " ".join(s.capitalize() for s in title_segments[name_start:])
            
        paper_id = source_id + "_" + title.replace(": ", "_").replace(" ", "-").lower()

        with conn.cursor() as cur:
            upsert_row(
                cur,
                table="paper",
                row={
                    "paper_id": paper_id,
                    "source": source,
                    "title": title,
                    "authors": ["Jarod Alper"], # TODO: Add support
                    "link": ""
                },
                on_conflict={
                    "with": ["paper_id"],
                    "replace": ["title"]
                }
            )

        conn.commit()

        batch_theorems = []

        print(title)
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
        "--folder-link",
        required=False,
        help="Google Drive link to folder of JSON files"
    )

    arg_parser.add_argument(
        "--source",
        required=True,
        help="Name of source"
    )

    arg_parser.add_argument(
        "--source-link",
        required=True,
        help="Link to source"
    )

    args = arg_parser.parse_args()

    _upsert_theorems_from_json(
        folder_link=args.folder_link,
        source=args.source,
        source_link=args.source_link
    )