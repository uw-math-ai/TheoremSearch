#!/usr/bin/env python3
"""
Count LaTeX packages used in arxiv_paper_metadata preambles and write a CSV.

Columns: package, count, percentage

Usage:
    python preamble_packages.py [--output packages.csv] [--top-k 20]
"""

import argparse
import csv
import re
import sys
from collections import Counter

import tqdm

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from rds.utils.connect import get_rds_connection
from rds.utils.query import get_query_count
from rds.utils.paginate import paginate_query

BASE_QUERY = "SELECT arxiv_id, preamble FROM arxiv_paper_metadata WHERE preamble IS NOT NULL"


def extract_packages(preamble: str) -> list[str]:
    """Return all package names from \\usepackage calls in a preamble."""
    packages = []
    for match in re.finditer(r"\\usepackage(?:\[[^\]]*\])?\{([^}]+)\}", preamble):
        for pkg in match.group(1).split(","):
            pkg = pkg.strip()
            if pkg:
                packages.append(pkg)
    return packages


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Count common LaTeX packages in arxiv_paper_metadata preambles."
    )
    parser.add_argument(
        "--output",
        default="packages.csv",
        help="Output CSV file path (default: packages.csv).",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        metavar="K",
        help="Only emit the top K packages by count.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    conn = get_rds_connection()
    try:
        total = get_query_count(conn, BASE_QUERY)
        if total == 0:
            print("No preambles found.", file=sys.stderr)
            return 1

        counter: Counter = Counter()
        with tqdm.tqdm(total=total, desc="Scanning preambles", unit="paper") as bar:
            for page in paginate_query(conn, BASE_QUERY, order_by="arxiv_id", page_size=500):
                for row in page:
                    for pkg in extract_packages(row["preamble"]):
                        counter[pkg] += 1
                bar.update(len(page))
    finally:
        conn.close()

    entries = counter.most_common(args.top_k)

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["package", "count", "percentage"])
        for pkg, count in entries:
            percentage = round(count / total * 100, 4)
            writer.writerow([pkg, count, percentage])

    print(f"Wrote {len(entries)} packages to {args.output} ({total} papers total).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
