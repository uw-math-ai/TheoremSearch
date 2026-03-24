import re
from collections import defaultdict
from tqdm import tqdm
from argparse import ArgumentParser
from rds.utils.connect import get_rds_connection
from rds.utils.query import build_query, get_query_count
from rds.utils.paginate import paginate_query
from rds.utils.upsert import upsert_rows
from ..printing import print_script_header

REF_RE = re.compile(
    r'\\(?:[a-zA-Z]*[Rr]ef|autoref|cref|Cref|eqref)\s*\{([^}]*)\}'
    r'|\\hyperref\s*\[([^\]]*)\]'
)

def _process_paper(statements: list, paper_id: str) -> list:
    label_to_statement_id = {s["label"]: s["statement_id"] for s in statements if s["label"]}

    if not label_to_statement_id:
        return []

    escaped_labels = {label: re.escape(label) for label in label_to_statement_id}
    dependency_rows = []

    for statement in statements:
        matched_labels = set()
        searchable_text = " ".join(filter(None, [statement["body"], statement["note"], statement["proof"]]))
        for m in REF_RE.finditer(searchable_text):
            content = m.group(1) or m.group(2)
            for label in label_to_statement_id:
                if re.search(r'\b' + escaped_labels[label] + r'\b', content):
                    matched_labels.add(label)

        for label in matched_labels:
            dependency_rows.append({
                "source_id": statement["statement_id"],
                "cite_id": paper_id,
                "dep_key": label,
                "dep_id": label_to_statement_id[label],
                "kind": "references",
                "interpaper": False
            })

    return dependency_rows

def connect_intrapaper_dependencies(
        condition: str, 
        condition_params: list[str], 
        batch_size: int, 
        overwrite: bool
    ):
    """
    Connects intrapaper theorem dependencies.

    Parameters
    ----------
    condition: str
        Condition to filter papers by
    condition_params: list[str]
        Parameters for condition
    batch_size : int
        Number of papers to connect dependencies for in a batch
    overwrite : bool
        Whether to overwrite dependency rows or not
    """

    print_script_header(
        action="Connecting intrapaper theorem dependencies",
        params={
            "condition": condition,
            "condition params?": condition_params,
            "batch size": batch_size,
            "overwrite": overwrite
        }
    )

    conn = get_rds_connection("v2")

    query, params = build_query(
        base_query="SELECT paper_id from paper",
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
                "params": condition_params
            }
        ]
    )

    count = get_query_count(conn, query)

    with tqdm(total=count, dynamic_ncols=True, unit=" papers") as pbar:
        for papers in paginate_query(
            conn,
            base_query=query,
            base_params=params,
            order_by="paper_id",
            page_size=batch_size
        ):
            paper_ids = [p["paper_id"] for p in papers]

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT statement.statement_id, statement.paper_id, im.label, im.note, statement.body, statement.proof
                    FROM statement
                    INNER JOIN informal_metadata im
                        ON im.statement_id = statement.statement_id
                    WHERE statement.paper_id::TEXT = ANY(%s)
                    """,
                    (paper_ids,)
                )
                batch_statements = [
                    {
                        key: val
                        for key, val in zip(["statement_id", "paper_id", "label", "note", "body", "proof"], row)
                    }
                    for row in cur.fetchall()
                ]

            statements_by_paper = defaultdict(list)
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

if __name__ == "__main__":
    arg_parser = ArgumentParser()

    arg_parser.add_argument(
        "-c",
        "--condition",
        type=str,
        nargs="+",
        help="Condition to filter papers by"
    )

    arg_parser.add_argument(
        "-b",
        "--batch-size",
        type=int,
        default=64,
        help="Number of papers to connect dependencies for in a batch. Default, 64"
    )

    arg_parser.add_argument(
        "-o",
        "--overwrite",
        action="store_true",
        help="Whether to overwrite dependency rows or not. Default, false"
    )

    args = arg_parser.parse_args()

    if args.condition and len(args.condition) >= 2:
        condition, *condition_params = args.condition
    else:
        condition = args.condition[0] if args.condition else None
        condition_params = []

    connect_intrapaper_dependencies(
        condition=condition,
        condition_params=condition_params,
        batch_size=args.batch_size,
        overwrite=args.overwrite
    )