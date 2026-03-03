import re
from collections import defaultdict
from tqdm import tqdm
from argparse import ArgumentParser
from rds.utils.connect import get_rds_connection
from rds.utils.query import get_query_count
from rds.utils.paginate import paginate_query
from rds.utils.upsert import upsert_rows
from ..printing import print_script_header

REF_RE = re.compile(
    r'\\(?:[a-zA-Z]*[Rr]ef|autoref|cref|Cref|eqref)\s*\{([^}]*)\}'
    r'|\\hyperref\s*\[([^\]]*)\]'
)

def _process_paper(theorems: list) -> list:
    label_to_theorem_id = {t["label"]: t["id"] for t in theorems if t["label"]}

    if not label_to_theorem_id:
        return []

    escaped_labels = {label: re.escape(label) for label in label_to_theorem_id}
    dependency_rows = []

    for theorem in theorems:
        matched_labels = set()
        searchable_text = " ".join(filter(None, [theorem["body"], theorem["note"], theorem["proof"]]))
        for m in REF_RE.finditer(searchable_text):
            content = m.group(1) or m.group(2)
            for label in label_to_theorem_id:
                if re.search(r'\b' + escaped_labels[label] + r'\b', content):
                    matched_labels.add(label)

        for label in matched_labels:
            dependency_rows.append({
                "src_theorem_id": theorem["id"],
                "dep_key": label,
                "dep_theorem_id": label_to_theorem_id[label],
                "interpaper": False
            })

    return dependency_rows

def connect_intrapaper_dependencies(batch_size: int, overwrite: bool):
    """
    Connects intrapaper theorem dependencies.

    Parameters
    ----------
    batch_size : int
        Number of papers to connect dependencies for in a batch
    overwrite : bool
        Whether to overwrite dependency rows or not
    """

    print_script_header(
        action="Connecting intrapaper theorem dependencies",
        params={
            "batch size": batch_size,
            "overwrite": overwrite
        }
    )

    conn = get_rds_connection("v2")

    if overwrite:
        query = """
            SELECT id, source FROM paper
            WHERE EXISTS (
                SELECT 1 FROM theorem 
                WHERE theorem.paper_id = paper.id
                    AND theorem.source = paper.source
            )
        """
    else:
        query = """
            SELECT id, source FROM paper
            WHERE EXISTS (
                SELECT 1 FROM theorem 
                WHERE theorem.paper_id = paper.id
                    AND theorem.source = paper.source
            )
            AND NOT EXISTS (
                SELECT 1 FROM theorem
                JOIN theorem_dependency ON theorem_dependency.src_theorem_id = theorem.id
                WHERE theorem.paper_id = paper.id
                    AND theorem.source = paper.source
                    AND theorem_dependency.interpaper IS FALSE
            )
        """

    count = get_query_count(conn, query)

    with tqdm(total=count, dynamic_ncols=True, unit=" papers") as pbar:
        for papers in paginate_query(
            conn,
            base_query=query,
            order_by="id",
            page_size=batch_size
        ):
            paper_ids = [p["id"] for p in papers]
            sources = [p["source"] for p in papers]

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, paper_id, label, note, body, proof FROM theorem WHERE paper_id = ANY(%s) AND source = ANY(%s)",
                    (paper_ids, sources)
                )
                batch_theorems = [
                    {
                        key: val
                        for key, val in zip(["id", "paper_id", "label", "note", "body", "proof"], row)
                    }
                    for row in cur.fetchall()
                ]

            theorems_by_paper = defaultdict(list)
            for t in batch_theorems:
                theorems_by_paper[t["paper_id"]].append(t)

            batch_rows = []
            for paper in papers:
                batch_rows.extend(_process_paper(theorems_by_paper[paper["id"]]))

            if batch_rows:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM theorem_dependency
                        WHERE interpaper IS FALSE
                            AND src_theorem_id::TEXT = ANY(%s)
                        """,
                        (list({row["src_theorem_id"] for row in batch_rows}),)
                    )

                upsert_rows(conn, table="theorem_dependency", rows=batch_rows)
                conn.commit()

            pbar.update(len(papers))

if __name__ == "__main__":
    arg_parser = ArgumentParser()

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

    connect_intrapaper_dependencies(
        batch_size=args.batch_size,
        overwrite=args.overwrite
    )