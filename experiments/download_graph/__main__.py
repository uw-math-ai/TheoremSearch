"""
Download a paper's dependency graph from the RDS and save it to JSON.

Usage:
    python -m experiments.download_graph 0706.2428
    python -m experiments.download_graph 0706.2428 -o my_graph.json
    python -m experiments.download_graph 0706.2428 --method llm heuristic
"""

import json
import sys
from argparse import ArgumentParser
from pathlib import Path

from rds.utils.connect import get_rds_connection


_ALL_SECTIONS = {"paper", "statements", "dependencies", "notation"}


def download_graph(
    external_id: str,
    methods: list[str] | None = None,
    include: set[str] = _ALL_SECTIONS,
) -> dict:
    conn = get_rds_connection("v2")
    with conn.cursor() as cur:
        # Paper metadata
        cur.execute(
            """
            SELECT p.paper_id, p.external_id, p.title, p.url,
                   p.authors, apm.abstract
            FROM paper p
            LEFT JOIN arxiv_paper_metadata apm ON apm.arxiv_id = p.external_id
            WHERE p.external_id = %s AND p.kind = 'paper'
            """,
            (external_id,),
        )
        row = cur.fetchone()
        if row is None:
            print(f"No paper found with external_id '{external_id}'.", file=sys.stderr)
            sys.exit(1)
        paper_id, ext_id, title, url, authors, abstract = row

        need_stmts = "statements" in include or "dependencies" in include or "notation" in include

        stmt_rows = []
        if need_stmts:
            cur.execute(
                """
                SELECT s.statement_id, s.kind, im.ref, s.body, s.proof, im.note
                FROM statement s
                JOIN informal_metadata im ON im.statement_id = s.statement_id
                WHERE s.paper_id = %s
                ORDER BY im.ordinal
                """,
                (paper_id,),
            )
            stmt_rows = cur.fetchall()

        notation_rows = []
        if "notation" in include and stmt_rows:
            stmt_ids = [str(r[0]) for r in stmt_rows]
            cur.execute(
                """
                SELECT statement_id, pattern, description
                FROM notation
                WHERE statement_id = ANY(%s::uuid[])
                ORDER BY statement_id
                """,
                (stmt_ids,),
            )
            notation_rows = cur.fetchall()

        dep_rows = []
        if "dependencies" in include:
            method_filter = ""
            method_params: list = [paper_id]
            if methods:
                placeholders = ", ".join(["%s"] * len(methods))
                method_filter = f" AND d.method IN ({placeholders})"
                method_params += methods

            cur.execute(
                f"""
                SELECT d.src_id, d.dep_id, d.cite_id, d.cite_key,
                       d.dep_name, d.dep_key, d.location, d.method,
                       dep_p.external_id AS dep_paper_ext_id
                FROM informal_dependency d
                JOIN statement s ON s.statement_id = d.src_id
                LEFT JOIN statement dep_s ON dep_s.statement_id = d.dep_id
                LEFT JOIN paper dep_p ON dep_p.paper_id = dep_s.paper_id
                                      OR dep_p.paper_id = d.cite_id
                WHERE s.paper_id = %s
                  AND (d.cite_key IS NULL OR d.cite_id IS NOT NULL)
                {method_filter}
                """,
                method_params,
            )
            dep_rows = cur.fetchall()

    # Build statement name lookup (needed for dep resolution even if statements not included)
    stmt_name: dict[str, str] = {}
    statements = []
    for sid, kind, ref, body, proof, note in stmt_rows:
        name = kind.capitalize() + (f" {ref}" if ref else "")
        stmt_name[str(sid)] = name
        statements.append({
            "kind":         kind,
            "ref":          ref,
            "name":         name,
            "body":         body,
            "proof":        proof,
            "note":         note,
        })

    dependencies = []
    for (src_id, dep_id, cite_id, cite_key,
         dep_name, dep_key, location, method, dep_paper_ext_id) in dep_rows:
        src_id_s = str(src_id)
        dep_id_s = str(dep_id) if dep_id else None
        dependencies.append({
            "src_name":         stmt_name.get(src_id_s, ""),
            "dep_name":         stmt_name.get(dep_id_s, "") if dep_id_s else (dep_name or ""),
            "dep_paper_ext_id": dep_paper_ext_id,
            "cite_key":         cite_key,
            "dep_key":          dep_key,
            "location":         location,
            "method":           method,
        })

    result = {}
    if "paper" in include:
        result["paper"] = {
            "paper_id":    str(paper_id),
            "external_id": ext_id,
            "title":       title,
            "authors":     authors or [],
            "abstract":    abstract,
            "url":         url,
        }
    if "statements" in include:
        result["statements"] = statements
    if "dependencies" in include:
        result["dependencies"] = dependencies
    if "notation" in include:
        result["notation"] = [
            {
                "statement_name": stmt_name.get(str(sid), ""),
                "pattern":     pattern,
                "description": description,
            }
            for sid, pattern, description in notation_rows
        ]
    return result


if __name__ == "__main__":
    parser = ArgumentParser(description="Download a paper's dependency graph to JSON.")
    parser.add_argument("external_id", help="Paper external ID (e.g. arXiv ID: 0706.2428)")
    parser.add_argument("-o", "--output", type=str, default=None,
                        help="Output file path. Default: <external_id>_graph.json")
    parser.add_argument("--method", nargs="+", default=None,
                        dest="methods",
                        help="Filter by method(s): deterministic heuristic llm. Default: all.")
    parser.add_argument("--include", nargs="+",
                        choices=sorted(_ALL_SECTIONS), default=None,
                        help="Sections to include: paper statements dependencies. Default: all.")

    args = parser.parse_args()

    out_path = Path(args.output) if args.output else Path(f"{args.external_id}_graph.json")

    include = set(args.include) if args.include else _ALL_SECTIONS
    data = download_graph(args.external_id, methods=args.methods, include=include)

    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    parts = []
    if "statements"   in data: parts.append(f"{len(data['statements'])} statements")
    if "dependencies" in data: parts.append(f"{len(data['dependencies'])} dependencies")
    if "notation"     in data: parts.append(f"{len(data['notation'])} notation entries")
    print(f"Saved {', '.join(parts) or 'paper info only'} → {out_path}")
