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


def _process_paper(statements: list) -> list:
    label_to_dep = {
        s["label"]: s["statement_id"]
        for s in statements
        if s["label"]
    }
    if not label_to_dep:
        return []

    dependency_rows = []
    for statement in statements:
        for location, text in [
            ("body",  statement["body"]),
            ("note",  statement["note"]),
            ("proof", statement["proof"]),
        ]:
            if not text:
                continue
            seen = set()
            for m in _REF_RE.finditer(text):
                content = m.group(1) or m.group(2)
                if not content:
                    continue
                for label in (lbl.strip() for lbl in content.split(',')):
                    if label in label_to_dep and label not in seen:
                        seen.add(label)
                        dependency_rows.append({
                            "src_id":   statement["statement_id"],
                            "location": location,
                            "cite_id":  None,
                            "cite_key": None,
                            "dep_key":  label,
                            "dep_id":   label_to_dep[label],
                            "dep_name": None,
                        })

    return dependency_rows


def connect_intrapaper_dependencies(
    conn: connection,
    condition: str,
    condition_params: List[str],
    batch_size: int,
    overwrite: bool,
    shard: int = 0,
    n_shards: int = 1,
):
    query, params = build_query(
        base_query=(
            "SELECT paper_id FROM paper"
            + (" LEFT JOIN arxiv_paper_metadata AS apm ON apm.arxiv_id = paper.external_id" if condition and "apm." in condition else "")
            + (" LEFT JOIN arxiv_parse_status AS aps ON aps.arxiv_id = paper.external_id" if condition and "aps." in condition else "")
        ),
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
                        JOIN informal_dependency ON informal_dependency.src_id = statement.statement_id
                        WHERE statement.paper_id = paper.paper_id
                          AND informal_dependency.cite_key IS NULL
                    )
                """
            },
            {
                "if": condition,
                "condition": condition,
                "params": condition_params,
            },
            {
                "if": n_shards > 1,
                "condition": "hashtext(paper_id::text) %% %s = %s",
                "params": [n_shards, shard],
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
                    WHERE s.paper_id = ANY(%s::uuid[])
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
                batch_rows.extend(_process_paper(statements_by_paper[paper["paper_id"]]))

            if batch_rows:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM informal_dependency
                        WHERE cite_key IS NULL
                          AND src_id = ANY(%s::uuid[])
                        """,
                        (list({row["src_id"] for row in batch_rows}),)
                    )
                upsert_rows(conn, table="informal_dependency", rows=batch_rows)
                conn.commit()

            pbar.update(len(papers))
