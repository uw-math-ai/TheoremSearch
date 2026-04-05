import re
from collections import defaultdict
from typing import List, Dict
from tqdm import tqdm
from psycopg2.extensions import connection

from rds.utils.query import build_query, get_query_count
from rds.utils.paginate import paginate_query
from rds.utils.upsert import upsert_rows

_REF_RE = re.compile(
    r'\\(?:[a-zA-Z]*[Rr]ef|autoref|cref|Cref|eqref)\s*\{([^}]*)\}'
    r'|\\hyperref\s*\[([^\]]*)\]'
)


def _process_paper(statements: list, paper_id: str) -> list:
    label_to_statement_id = {s["label"]: s["statement_id"] for s in statements if s["label"]}
    if not label_to_statement_id:
        return []

    dependency_rows = []
    for statement in statements:
        matched_labels = set()
        searchable_text = " ".join(filter(None, [statement["body"], statement["note"], statement["proof"]]))

        for m in _REF_RE.finditer(searchable_text):
            content = m.group(1) or m.group(2)
            # Each ref contains a comma-separated list of labels; a set lookup
            # is O(1) vs the previous O(N) per-label regex scan.
            for ref in (r.strip() for r in content.split(',')):
                if ref in label_to_statement_id:
                    matched_labels.add(ref)

        for label in matched_labels:
            dependency_rows.append({
                "source_id": statement["statement_id"],
                "cite_id":   paper_id,
                "dep_key":   label,
                "dep_id":    label_to_statement_id[label],
                "kind":      "references",
                "interpaper": False,
            })

    return dependency_rows


def connect_intrapaper_dependencies(
    conn: connection,
    condition: str,
    condition_params: List[str],
    batch_size: int,
    overwrite: bool,
):
    query, params = build_query(
        base_query="SELECT paper_id FROM paper",
        where_clauses=[
            {
                "if": True,
                "condition": """
                    EXISTS (
                        SELECT 1 FROM statement
                        WHERE statement.paper_id = paper.paper_id
                    )
                """
            },
            {
                "if": not overwrite,
                "condition": """
                    NOT EXISTS (
                        SELECT 1 FROM statement
                        JOIN dependency ON dependency.source_id = statement.statement_id
                        WHERE statement.paper_id = paper.paper_id
                          AND dependency.interpaper IS FALSE
                    )
                """
            },
            {
                "if": condition,
                "condition": condition,
                "params": condition_params,
            },
        ]
    )

    count = get_query_count(conn, query, params)

    with tqdm(total=count, dynamic_ncols=True, unit=" papers", desc="Intrapaper") as pbar:
        for papers in paginate_query(
            conn,
            base_query=query,
            base_params=params,
            order_by="paper_id",
            page_size=batch_size,
        ):
            paper_ids = [p["paper_id"] for p in papers]

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT s.statement_id, s.paper_id, im.label, im.note, s.body, s.proof
                    FROM statement s
                    INNER JOIN informal_metadata im ON im.statement_id = s.statement_id
                    WHERE s.paper_id::TEXT = ANY(%s)
                    """,
                    (paper_ids,)
                )
                batch_statements = [
                    dict(zip(["statement_id", "paper_id", "label", "note", "body", "proof"], row))
                    for row in cur.fetchall()
                ]

            statements_by_paper: Dict[str, list] = defaultdict(list)
            for s in batch_statements:
                statements_by_paper[s["paper_id"]].append(s)

            batch_rows = []
            for paper in papers:
                batch_rows.extend(_process_paper(statements_by_paper[paper["paper_id"]], paper["paper_id"]))

            if batch_rows:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM dependency
                        WHERE interpaper IS FALSE
                          AND source_id::TEXT = ANY(%s)
                        """,
                        (list({row["source_id"] for row in batch_rows}),)
                    )
                upsert_rows(conn, table="dependency", rows=batch_rows)
                conn.commit()

            pbar.update(len(papers))
