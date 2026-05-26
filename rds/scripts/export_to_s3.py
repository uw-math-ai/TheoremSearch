"""
Export RDS tables to S3 as CSV files.

Tables exported (one CSV per file in S3_BUCKET):
    paper_arxiv          – paper JOIN arxiv_paper_metadata
    paper_lean_community – paper JOIN lean_community_paper_metadata
    paper_lean_repo      – paper JOIN lean_repo_metadata
    statement_informal   – statement JOIN informal_metadata  (license-gated content)
    statement_formal     – statement JOIN formal_metadata    (license-gated content)
    informal_dependency  – informal_dependency
    formal_dependency    – formal_dependency
    slogan               – slogan (restricted-paper rows omitted entirely)

Content gating: statement body, proof, note, pre_context, and post_context are
replaced with NULL unless the associated paper's license is in OPEN_LICENSES.
Lean Community papers are always treated as open (no license field in the schema).
All other papers without a license entry (e.g. Lean Repo) are treated as restricted.

Usage:
    python export_to_s3.py [--db v2]
"""

import argparse
import csv
import io
import os
import sys

import boto3
from botocore.exceptions import ClientError
from tqdm import tqdm

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from utils.connect import get_rds_connection

# ---------------------------------------------------------------------------
# Configuration — edit before running
# ---------------------------------------------------------------------------

S3_BUCKET = "math-graph-bucket"  # e.g. "my-export-bucket"

# List column names to omit from each output file (post-alias names).
# An empty list means include all columns.
EXCLUDED_FIELDS: dict[str, list[str]] = {
    "paper_arxiv":          ["preamble", "bibliography", "bibtex", "in_validation"],
    "paper_lean_community": ["preamble", "bibliography", "bibtex"],
    "paper_lean_repo":      [],
    "statement_informal":   [],
    "statement_formal":     [],
    "informal_dependency":  [],
    "formal_dependency":    [],
    "slogan":               ["created_at"],
}

# arXiv licenses whose content may be published.
# Excluded (despite high volume):
#   arxiv.org/licenses/nonexclusive-distrib/1.0/ — arXiv-only distribution right, not for third-party republication
#   by-nc-nd/4.0/ and by-nc-nd/3.0/             — "no derivatives" bars dataset compilation
#   by-nc-sa/4.0/ and by-nc-sa/3.0/             — non-commercial only; add these if the dataset is non-commercial
#   NULL                                          — unknown license, excluded
OPEN_LICENSES = (
    "http://creativecommons.org/publicdomain/zero/1.0/",  # CC0
    "http://creativecommons.org/licenses/publicdomain/",  # CC Public Domain
    "http://creativecommons.org/licenses/by/4.0/",        # CC BY 4.0
    "http://creativecommons.org/licenses/by/3.0/",        # CC BY 3.0
    "http://creativecommons.org/licenses/by-sa/4.0/",     # CC BY-SA 4.0
)

# ---------------------------------------------------------------------------
# SQL queries
# ---------------------------------------------------------------------------

PAPER_ARXIV_QUERY = """
SELECT
    p.paper_id, p.kind, p.source, p.title, p.authors, p.url,
    p.categories, p.updated_at,
    am.arxiv_id, am.journal_ref, am.doi, am.license, am.abstract, am.preamble,
    am.bibliography, am.bibtex, am.citation_count, am.reference_ids,
    am.in_validation
FROM paper p
JOIN arxiv_paper_metadata am ON am.arxiv_id = p.external_id
WHERE p.source = 'arXiv'
"""

PAPER_LEAN_COMMUNITY_QUERY = """
SELECT
    p.paper_id, p.kind, p.source, p.title, p.authors, p.url,
    p.categories, p.updated_at,
    split_part(lm.repo_slug, '/', 2) AS repo_slug,
    lm.branch, lm.src_path, lm.preamble, lm.bibliography, lm.bibtex
FROM paper p
JOIN lean_community_paper_metadata lm ON lm.repo_slug = p.external_id
WHERE p.source = 'Lean Community'
"""

PAPER_LEAN_REPO_QUERY = """
SELECT
    p.paper_id, p.kind, p.source, p.title, p.authors, p.url,
    p.categories, p.updated_at,
    lrm.repo_slug, lrm.repo_url, lrm.lean_toolchain, lrm.mathlib_rev, lrm.git_commit
FROM paper p
JOIN lean_repo_metadata lrm ON lrm.repo_slug = p.external_id
WHERE p.source = 'Lean Repo'
"""

# Identifies papers whose statement content may be exported.
# Lean Community: always open (no license field in schema).
# arXiv: open only when license is in OPEN_LICENSES.
# All others (e.g. Lean Repo): no license entry → treated as restricted.
_OPEN_PAPERS_CTE = """
WITH open_papers AS (
    SELECT p.paper_id
    FROM paper p
    LEFT JOIN arxiv_paper_metadata am
           ON am.arxiv_id = p.external_id AND p.source = 'arXiv'
    WHERE p.source = 'Lean Community'
       OR am.license = ANY(%(licenses)s)
)
"""

STATEMENT_INFORMAL_QUERY = (
    _OPEN_PAPERS_CTE
    + """
SELECT
    s.statement_id,
    s.paper_id,
    s.formality,
    s.kind,
    CASE WHEN op.paper_id IS NOT NULL THEN s.body        ELSE NULL END AS body,
    CASE WHEN op.paper_id IS NOT NULL THEN s.proof       ELSE NULL END AS proof,
    im.ordinal,
    im.ref,
    im.label,
    im.lean,
    CASE WHEN op.paper_id IS NOT NULL THEN im.note         ELSE NULL END AS note,
    CASE WHEN op.paper_id IS NOT NULL THEN im.pre_context  ELSE NULL END AS pre_context,
    CASE WHEN op.paper_id IS NOT NULL THEN im.post_context ELSE NULL END AS post_context
FROM statement s
JOIN  informal_metadata im ON im.statement_id = s.statement_id
LEFT JOIN open_papers   op ON op.paper_id     = s.paper_id
"""
)

STATEMENT_FORMAL_QUERY = (
    _OPEN_PAPERS_CTE
    + """
SELECT
    s.statement_id,
    s.paper_id,
    s.formality,
    s.kind,
    CASE WHEN op.paper_id IS NOT NULL THEN s.body  ELSE NULL END AS body,
    CASE WHEN op.paper_id IS NOT NULL THEN s.proof ELSE NULL END AS proof,
    fm.file_path,
    fm.decl_name,
    fm.module,
    fm.docstring,
    fm.is_instance
FROM statement s
JOIN  formal_metadata fm ON fm.statement_id = s.statement_id
LEFT JOIN open_papers  op ON op.paper_id    = s.paper_id
"""
)

INFORMAL_DEPENDENCY_QUERY = "SELECT * FROM informal_dependency"
FORMAL_DEPENDENCY_QUERY = "SELECT * FROM formal_dependency"

# Slogans are omitted entirely (not NULLed) when the associated paper is restricted.
SLOGAN_QUERY = (
    _OPEN_PAPERS_CTE
    + """
SELECT sl.*
FROM slogan sl
JOIN statement s  ON s.statement_id = sl.statement_id
JOIN open_papers op ON op.paper_id  = s.paper_id
"""
)

# (name, query, params) — params is passed directly to cursor.execute()
EXPORTS = [
    ("paper_arxiv",          PAPER_ARXIV_QUERY,          None),
    ("paper_lean_community", PAPER_LEAN_COMMUNITY_QUERY, None),
    ("paper_lean_repo",      PAPER_LEAN_REPO_QUERY,      None),
    ("statement_informal",   STATEMENT_INFORMAL_QUERY,   {"licenses": list(OPEN_LICENSES)}),
    ("statement_formal",     STATEMENT_FORMAL_QUERY,     {"licenses": list(OPEN_LICENSES)}),
    ("informal_dependency",  INFORMAL_DEPENDENCY_QUERY,  None),
    ("formal_dependency",    FORMAL_DEPENDENCY_QUERY,    None),
    ("slogan",               SLOGAN_QUERY,               {"licenses": list(OPEN_LICENSES)}),
]

# ---------------------------------------------------------------------------
# Export logic
# ---------------------------------------------------------------------------

def _exists_in_s3(s3, key: str) -> bool:
    try:
        s3.head_object(Bucket=S3_BUCKET, Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return False
        raise


def _upload_csv(s3, conn, name: str, query: str, params, fetch_size: int) -> None:
    excluded = set(EXCLUDED_FIELDS.get(name, []))
    s3_key = f"{name}.csv"

    if _exists_in_s3(s3, s3_key):
        print(f"  {s3_key}: already exists, skipping")
        return

    buf = io.StringIO()
    writer = csv.writer(buf)
    row_count = 0

    with conn.cursor(name=f"cursor_{name}") as cur:
        cur.itersize = fetch_size
        cur.execute(query, params)

        # description is None until after the first fetch on a named cursor
        rows = cur.fetchmany(fetch_size)
        col_names = [d[0] for d in cur.description]
        keep = [i for i, c in enumerate(col_names) if c not in excluded]
        writer.writerow([col_names[i] for i in keep])

        with tqdm(unit="row", desc=f"  {s3_key}", leave=True) as pbar:
            while rows:
                for row in rows:
                    writer.writerow([row[i] for i in keep])
                pbar.update(len(rows))
                row_count += len(rows)
                rows = cur.fetchmany(fetch_size)

    body = buf.getvalue().encode("utf-8")
    s3.put_object(Bucket=S3_BUCKET, Key=s3_key, Body=body, ContentType="text/csv")
    tqdm.write(f"  {s3_key}: {row_count:,} rows, {len(body) / 1024:.1f} KB")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export RDS tables to S3 as CSV.")
    parser.add_argument("--db",         default="v2",    help="Database name (default: v2)")
    parser.add_argument("--fetch-size", default=50_000,  type=int, help="Rows fetched per batch (default: 50000)")
    args = parser.parse_args()

    if not S3_BUCKET:
        print("Error: S3_BUCKET is not set. Edit the constant at the top of this script.")
        sys.exit(1)

    print(f"Connecting to database '{args.db}'…")
    conn = get_rds_connection(args.db)
    conn.autocommit = False  # required for server-side (named) cursors

    s3 = boto3.client("s3")
    print(f"Exporting to s3://{S3_BUCKET}/\n")

    try:
        for name, query, params in EXPORTS:
            _upload_csv(s3, conn, name, query, params, args.fetch_size)
    finally:
        conn.rollback()  # read-only export; rollback cleans up the open transaction
        conn.close()

    print("\nDone.")


if __name__ == "__main__":
    main()
