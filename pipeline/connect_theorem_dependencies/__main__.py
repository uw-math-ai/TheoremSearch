import re
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from rds.utils.connect import get_rds_connection
from rds.utils.query import get_query_count
from rds.utils.paginate import paginate_query
from rds.utils.upsert import update_rows
from ..printing import print_script_header

def _has_label_ref(body: str, label: str) -> bool:
    pattern = r'\\[a-zA-Z]*[Rr]ef\{' + re.escape(label) + r'\}'
    return bool(re.search(pattern, body))

def _process_paper(paper) -> list:
    conn = get_rds_connection("v2")

    try:
        paper_id = paper["id"]
        source = paper["source"]

        label_to_theorem_id = {}
        paper_theorems = []

        for theorems in paginate_query(
            conn,
            base_query="SELECT * FROM theorem WHERE paper_id = %s AND source = %s",
            base_params=[paper_id, source],
            order_by="id",
            page_size=100
        ):
            paper_theorems.extend(theorems)

            for theorem in theorems:
                if theorem["label"]:
                    if theorem["label"] not in label_to_theorem_id:
                        label_to_theorem_id[theorem["label"]] = []

                    label_to_theorem_id[theorem["label"]].append(theorem["id"])

        dependency_rows = []

        for theorem in paper_theorems:
            theorem_dependencies = []

            for label, theorem_dependency_ids in label_to_theorem_id.items():
                if _has_label_ref(theorem["body"], label):
                    theorem_dependencies.extend(theorem_dependency_ids)

            if theorem_dependencies:
                dependency_rows.append({
                    "id": theorem["id"],
                    "theorem_dependencies": theorem_dependencies
                })

        return dependency_rows
    finally:
        conn.close()

def connect_theorem_dependencies(batch_size: int, workers: int = 4):
    """
    Connects inter-paper theorem dependencies
    """
    print_script_header(
        action="Connecting inter-paper theorem dependencies",
        params={
            "batch size": batch_size,
            "workers": workers
        }
    )

    conn = get_rds_connection("v2")

    query = """
        SELECT id, source FROM paper
        WHERE EXISTS (
            SELECT 1 FROM theorem 
            WHERE theorem.paper_id = paper.id
                AND theorem.source = paper.source
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
            batch_theorem_dependency_rows = []

            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(_process_paper, paper): paper for paper in papers}

                for future in as_completed(futures):
                    batch_theorem_dependency_rows.extend(future.result())

            if batch_theorem_dependency_rows:
                update_rows(
                    conn,
                    table="theorem",
                    rows=batch_theorem_dependency_rows,
                    where=["id"]
                )

                conn.commit()

            pbar.update(len(papers))

if __name__ == "__main__":
    connect_theorem_dependencies(batch_size=16, workers=4)