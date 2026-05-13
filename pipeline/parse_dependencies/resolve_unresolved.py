"""
Patch existing unresolved inter-paper cite_keys using updated resolution logic
(Semantic Scholar reference_ids as candidate pool).

Reads informal_dependency rows where cite_key IS NOT NULL AND cite_id IS NULL,
groups them by source paper, and attempts resolution without re-parsing statements.

Usage:
    python -m pipeline.parse_dependencies.resolve_unresolved
    python -m pipeline.parse_dependencies.resolve_unresolved -s 0.7
    python -m pipeline.parse_dependencies.resolve_unresolved -c "apm.arxiv_id = %s" 1234.5678
"""

import sys
from argparse import ArgumentParser
from pathlib import Path
from tqdm import tqdm
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from rds.utils.connect import get_rds_connection
from pipeline.printing import print_script_header
from pipeline.parse_dependencies.interpaper import (
    _resolve_bib_keys, _resolve_dep_ids, _parse_dep_name,
)


def resolve_unresolved(
    conn,
    similarity_threshold: float,
    batch_size: int,
    condition: Optional[str],
    condition_params: list,
):
    where = (
        "WHERE d.cite_key IS NOT NULL AND d.cite_id IS NULL AND paper.kind = 'paper'"
        + (f" AND ({condition})" if condition else "")
    )
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT DISTINCT paper.paper_id, paper.external_id
            FROM informal_dependency d
            JOIN statement s ON s.statement_id = d.src_id
            JOIN paper ON paper.paper_id = s.paper_id
            LEFT JOIN arxiv_paper_metadata apm ON apm.arxiv_id = paper.external_id
            {where}
            ORDER BY paper.paper_id
            """,
            condition_params or None,
        )
        papers = cur.fetchall()

    cite_ids_resolved = 0
    dep_ids_resolved = 0

    with tqdm(total=len(papers), unit=" papers", desc="Resolving", dynamic_ncols=True) as pbar:
        for i in range(0, len(papers), batch_size):
            batch = papers[i : i + batch_size]

            for paper_id, arxiv_id in batch:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT bibliography, bibtex, reference_ids FROM arxiv_paper_metadata WHERE arxiv_id = %s",
                        (arxiv_id,),
                    )
                    row = cur.fetchone()

                if not row or not row[0]:
                    pbar.update(1)
                    continue

                bib = row[0]
                bibtex = bool(row[1]) if row[1] is not None else True
                reference_ids = row[2]

                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT d.src_id, d.cite_key, d.dep_name
                        FROM informal_dependency d
                        JOIN statement s ON s.statement_id = d.src_id
                        WHERE s.paper_id = %s
                          AND d.cite_key IS NOT NULL
                          AND d.cite_id IS NULL
                        """,
                        (paper_id,),
                    )
                    dep_rows = cur.fetchall()

                if not dep_rows:
                    pbar.update(1)
                    continue

                unresolved_keys = {r[1] for r in dep_rows}
                needed_bib = {k: v for k, v in bib.items() if k in unresolved_keys}
                if not needed_bib:
                    pbar.update(1)
                    continue

                resolved = _resolve_bib_keys(
                    conn, needed_bib, similarity_threshold,
                    bibtex=bibtex, reference_ids=reference_ids,
                )
                if not resolved:
                    pbar.update(1)
                    continue

                # Build dep_id lookups: one per (src_id, cite_key) that has a parseable dep_name.
                lookups = []
                for src_id, cite_key, dep_name in dep_rows:
                    cite_id = resolved.get(cite_key)
                    if not cite_id or not dep_name:
                        continue
                    ttype, tref = _parse_dep_name(dep_name)
                    if ttype and tref:
                        lookups.append((str(cite_id), ttype, tref))

                dep_id_cache = _resolve_dep_ids(conn, list(dict.fromkeys(lookups))) if lookups else {}

                for src_id, cite_key, dep_name in dep_rows:
                    cite_id = resolved.get(cite_key)
                    if not cite_id:
                        continue
                    ttype, tref = _parse_dep_name(dep_name) if dep_name else (None, None)
                    dep_id = dep_id_cache.get((str(cite_id), ttype, tref)) if (ttype and tref) else None

                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            UPDATE informal_dependency
                            SET cite_id = %s,
                                dep_id  = COALESCE(%s, dep_id)
                            WHERE src_id = %s
                              AND cite_key = %s
                              AND cite_id IS NULL
                            RETURNING (dep_id IS NOT NULL AND %s IS NOT NULL)
                            """,
                            (cite_id, dep_id, src_id, cite_key, dep_id),
                        )
                        row = cur.fetchone()
                        if row:
                            cite_ids_resolved += 1
                            if row[0]:
                                dep_ids_resolved += 1

                conn.commit()
                pbar.set_postfix({"cite_ids": cite_ids_resolved, "dep_ids": dep_ids_resolved})
                pbar.update(1)

    return cite_ids_resolved, dep_ids_resolved


if __name__ == "__main__":
    parser = ArgumentParser(
        description="Patch unresolved inter-paper cite_keys without re-parsing statements."
    )
    parser.add_argument(
        "-s", "--similarity-threshold",
        type=float,
        default=0.8,
        dest="similarity_threshold",
        help="pg_trgm title-match threshold (default: 0.8)",
    )
    parser.add_argument(
        "-b", "--batch-size",
        type=int,
        default=64,
        dest="batch_size",
        help="Papers processed per batch (default: 64)",
    )
    parser.add_argument(
        "-c", "--condition",
        type=str,
        nargs="+",
        help="SQL WHERE condition to filter source papers (first token is expression, rest are params)",
    )
    args = parser.parse_args()

    if args.condition and len(args.condition) >= 2:
        condition, *condition_params = args.condition
    else:
        condition = args.condition[0] if args.condition else None
        condition_params = []

    print_script_header(
        action="Resolving unresolved inter-paper cite_keys",
        params={
            "similarity threshold": args.similarity_threshold,
            "batch size":           args.batch_size,
            "condition?":           condition,
            "condition params?":    condition_params,
        },
    )

    conn = get_rds_connection("v2")
    try:
        cite_ids_resolved, dep_ids_resolved = resolve_unresolved(
            conn,
            similarity_threshold=args.similarity_threshold,
            batch_size=args.batch_size,
            condition=condition,
            condition_params=condition_params,
        )
    finally:
        conn.close()

    print(f"\nDone.")
    print(f"  cite_ids resolved: {cite_ids_resolved}")
    print(f"  dep_ids  resolved: {dep_ids_resolved}")
