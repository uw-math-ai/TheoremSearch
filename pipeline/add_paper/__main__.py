"""
Register a local LaTeX paper (e.g. a Lean blueprint) into the paper table.

The folder is tarballed, gzipped, and uploaded to S3 under ``s3://<bucket>/<kind>/<external_id>.tar.gz``.
A row is upserted into ``paper`` plus the source-specific metadata extension table
(e.g. ``reservoir_paper_metadata`` for Reservoir blueprints).
"""

import tarfile
import tempfile
from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from rds.utils.connect import get_rds_connection
from rds.utils.upsert import upsert_row
from s3.utils.io import upload_file
from ..constants import PAPERS_BUCKET
from ..printing import print_script_header


_SOURCE_METADATA_TABLE = {
    "Reservoir": ("reservoir_paper_metadata", "reservoir_slug"),
}


def _tar_gzip(folder: Path, out_path: Path) -> None:
    with tarfile.open(out_path, "w:gz") as tf:
        for entry in sorted(folder.iterdir()):
            tf.add(entry, arcname=entry.name)


def add_paper(
    path: Path,
    kind: str,
    source: str,
    external_id: str,
    title: str,
    authors: list[str],
    url: Optional[str],
    overwrite: bool,
):
    if not path.is_dir():
        raise NotADirectoryError(f"--path must be a directory: {path}")

    if not any(p.suffix == ".tex" for p in path.rglob("*")):
        raise ValueError(f"No .tex files found under {path}")

    s3_key = f"{kind}/{external_id}.tar.gz"
    s3_uri = f"s3://{PAPERS_BUCKET}/{s3_key}"

    print_script_header(
        action="Adding paper folder",
        params={
            "path": path,
            "kind": kind,
            "source": source,
            "external_id": external_id,
            "title": title,
            "authors": authors,
            "url?": url,
            "s3 destination": s3_uri,
            "overwrite": overwrite,
        }
    )

    conn = get_rds_connection("v2")

    if not overwrite:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM paper WHERE source = %s AND external_id = %s",
                (source, external_id),
            )
            if cur.fetchone() is not None:
                raise RuntimeError(
                    f"paper already exists for (source={source}, external_id={external_id}). "
                    "Pass --overwrite to replace."
                )

    print("Creating tarball...")
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        tarball_path = Path(tmp.name)
    try:
        _tar_gzip(path, tarball_path)
        size_mb = tarball_path.stat().st_size / (1024 * 1024)
        print(f"  Tarball: {tarball_path} ({size_mb:.2f} MB)")

        print(f"Uploading to {s3_uri}...")
        upload_file(tarball_path, s3_uri)
    finally:
        tarball_path.unlink(missing_ok=True)

    print("Upserting paper row...")
    upsert_row(
        conn,
        table="paper",
        row={
            "kind": kind,
            "source": source,
            "title": title,
            "authors": authors,
            "url": url,
            "external_id": external_id,
            "updated_at": datetime.now(timezone.utc),
        },
        on_conflict={
            "with": ["source", "external_id"],
            "replace": ["kind", "title", "authors", "url", "updated_at"],
        }
    )

    if source in _SOURCE_METADATA_TABLE:
        table, id_col = _SOURCE_METADATA_TABLE[source]
        print(f"Ensuring {table} row exists...")
        upsert_row(
            conn,
            table=table,
            row={id_col: external_id},
            on_conflict={
                "with": [id_col],
                # DO NOTHING — preserve any preamble/bibliography already there
            }
        )

    conn.commit()
    print("Done.")


if __name__ == "__main__":
    arg_parser = ArgumentParser(
        description="Register a local LaTeX paper folder (uploads to S3 and updates paper table)."
    )

    arg_parser.add_argument(
        "--path",
        type=Path,
        required=True,
        help="Path to the local folder containing the paper's LaTeX source."
    )

    arg_parser.add_argument(
        "--kind",
        type=str,
        required=True,
        choices=["paper", "blueprint", "textbook", "lean_repo", "open_project"],
        help="paper_kind. Determines the S3 folder (e.g. blueprint/, textbook/)."
    )

    arg_parser.add_argument(
        "--source",
        type=str,
        required=True,
        help="Upstream source (e.g. 'Reservoir' for Lean blueprints)."
    )

    arg_parser.add_argument(
        "--external-id",
        type=str,
        required=True,
        dest="external_id",
        help="Identifier within the source (e.g. Reservoir slug like 'apap')."
    )

    arg_parser.add_argument(
        "--title",
        type=str,
        required=True,
        help="Paper title."
    )

    arg_parser.add_argument(
        "--authors",
        type=str,
        required=True,
        help="Comma-separated author names."
    )

    arg_parser.add_argument(
        "--url",
        type=str,
        default=None,
        help="Canonical URL (e.g. blueprint homepage). Optional."
    )

    arg_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing an existing paper row for the same (source, external_id)."
    )

    args = arg_parser.parse_args()

    add_paper(
        path=args.path,
        kind=args.kind,
        source=args.source,
        external_id=args.external_id,
        title=args.title,
        authors=[a.strip() for a in args.authors.split(",") if a.strip()],
        url=args.url,
        overwrite=args.overwrite,
    )
