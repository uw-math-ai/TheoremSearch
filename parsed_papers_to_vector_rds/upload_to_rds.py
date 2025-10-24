"""
Script to upload parsed paper theorem metadata and embeddings into the AWS RDS databse.
"""

from theorem_formatting import get_theorem_metadata_and_embeddings
import json
from rds import get_rds_connection, upload_theorem_metadata_and_embeddings
from pathlib import Path

PARSED_PAPERS_DIR = Path("parsed_papers")
conn = get_rds_connection()

if __name__ == "__main__":
    N = len(list(PARSED_PAPERS_DIR.iterdir()))

    for i, parsed_paper_path in enumerate(PARSED_PAPERS_DIR.iterdir()):
        with open(parsed_paper_path, "r") as f:
            parsed_paper = json.load(f)

        theorem_metadata, theorem_embeddings = get_theorem_metadata_and_embeddings(parsed_paper)

        upload_theorem_metadata_and_embeddings(conn, theorem_metadata, theorem_embeddings)

        print(f"Formatted, embedded, and uploaded {parsed_paper_path} ({i+1}/{N})")