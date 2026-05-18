"""
Register a paper in the ``paper`` table.

Pure metadata registration — does not store source files anywhere. Per-source scrapers
(e.g. ``scrape_lean_community``) are responsible for populating their own
``<source>_paper_metadata`` extension table with whatever is needed to re-fetch the
LaTeX source at parse time.
"""

from argparse import ArgumentParser
from datetime import datetime, timezone
from typing import Optional

from rds.utils.connect import get_rds_connection
from rds.utils.upsert import upsert_row
from ..printing import print_script_header


def add_paper(
    kind: str,
    source: str,
    external_id: str,
    title: str,
    authors: list[str],
    url: Optional[str],
    overwrite: bool,
):
    print_script_header(
        action="Adding paper",
        params={
            "kind": kind,
            "source": source,
            "external_id": external_id,
            "title": title,
            "authors": authors,
            "url?": url,
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

    conn.commit()
    print("Done.")


if __name__ == "__main__":
    arg_parser = ArgumentParser(
        description="Register a paper row (no source file storage)."
    )

    arg_parser.add_argument(
        "--kind",
        type=str,
        required=True,
        choices=["paper", "blueprint", "textbook", "lean_repo", "open_project"],
        help="paper_kind."
    )

    arg_parser.add_argument(
        "--source",
        type=str,
        required=True,
        help="Upstream source (e.g. 'Lean Community', 'arXiv')."
    )

    arg_parser.add_argument(
        "--external-id",
        type=str,
        required=True,
        dest="external_id",
        help="Identifier within the source (e.g. 'teorth/pfr' for a GitHub repo slug, arXiv ID, etc.)."
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
        help="Canonical URL (e.g. blueprint PDF or repo URL). Optional."
    )

    arg_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing an existing paper row for the same (source, external_id)."
    )

    args = arg_parser.parse_args()

    add_paper(
        kind=args.kind,
        source=args.source,
        external_id=args.external_id,
        title=args.title,
        authors=[a.strip() for a in args.authors.split(",") if a.strip()],
        url=args.url,
        overwrite=args.overwrite,
    )
