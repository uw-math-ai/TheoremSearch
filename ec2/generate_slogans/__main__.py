"""
Given theorem filters, generates slogans for all theorems in 'theorem' satisfying the filters
and uploads them to the 'theorem_slogan' table in the RDS.
"""

from ..rds.connect import get_rds_connection
from ..rds.upsert import upsert_rows
import argparse
from ..rds.paginate import paginate_query
import os
import json
from .slogans import generate_theorem_slogans

def generate_slogans(
    model: str,
    prompt_id: str,
    paper_ids: list[str],
    authors: list[str],
    min_citations: int,
    in_journal: bool,
    overwrite: bool,
    page_size: int,
    workers: int
):
    conn = get_rds_connection()

    current_dir = os.path.dirname(__file__)
    path_to_prompt = os.path.join(
        os.path.dirname(current_dir),
        "slogan_prompts",
        prompt_id + ".prompt"
    )

    with open(path_to_prompt, "r") as f:
        prompt = json.loads(f.read())

    prompt["instructions"] = " ".join(prompt["instructions"])
    prompt["context"] = [c + " AS " + c.replace(".", "_") for c in prompt["context"]]

    select_cols = ", ".join(set(["theorem.theorem_id", *prompt["context"]]))

    base_sql = f"""
        SELECT {select_cols}
        FROM theorem
        INNER JOIN paper
        ON theorem.paper_id = paper.paper_id
    """
    count_sql = f"""
        SELECT COUNT(*)
        FROM theorem
        INNER JOIN paper
        ON theorem.paper_id = paper.paper_id
    """

    where_conditions = []
    base_params = []

    if not overwrite:
        where_conditions.append("""
            NOT EXISTS (
                SELECT 1
                FROM theorem_slogan AS ts
                WHERE ts.theorem_id = theorem.theorem_id
                    AND ts.model = %s
                    AND ts.prompt_id = %s
            )
        """)
        base_params.append(model)
        base_params.append(prompt_id)

    if paper_ids:
        where_conditions.append("paper.paper_id LIKE ANY(%s)")
        base_params.append(['%' + paper_id + '%' for paper_id in paper_ids])

    if authors:
        where_conditions.append("paper.authors && %s")
        base_params.append(authors)

    if min_citations >= 0:
        where_conditions.append("paper.citations >= %s")
        base_params.append(min_citations)

    if in_journal:
        where_conditions.append("paper.journal_ref IS NOT NULL")

    if where_conditions:
        base_sql += " WHERE " + " AND ".join(where_conditions)
        count_sql += " WHERE " + " AND ".join(where_conditions)

    with conn.cursor() as cur:
        cur.execute(count_sql, (*base_params,))
        n_results = cur.fetchone()[0]

    print(f"=== Generating slogans for {n_results} theorems (Model: {model}, Prompt: {prompt_id}) ===")
    n_theorems = 0

    for page, theorem_contexts in enumerate(paginate_query(
        conn,
        base_sql=base_sql,
        base_params=(*base_params,),
        order_by="theorem_id",
        descending=False,
        page_size=page_size
    )):
        n_theorems += len(theorem_contexts)
        print(f"[Page {1 + page}] {n_theorems}/{n_results}")

        slogans = generate_theorem_slogans(
            theorem_contexts,
            instructions=prompt["instructions"],
            model=model,
            max_workers=workers
        )
        
        with conn.cursor() as cur:
            upsert_rows(
                cur,
                table="theorem_slogan",
                rows=[
                    {
                        "theorem_id": theorem_context["theorem_id"],
                        "model": model,
                        "prompt_id": prompt_id,
                        "slogan": slogan
                    }
                    for slogan, theorem_context in zip(slogans, theorem_contexts)
                ],
                on_conflict={
                    "with": ["theorem_id", "model", "prompt_id"],
                    "replace": ["slogan"]
                }
            )

        conn.commit()

    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--model",
        type=str,
        required=True,
        help="Model (from LiteLLM) used to generate slogans"
    )

    parser.add_argument(
        "--prompt-id",
        type=str,
        required=True,
        help="Prompt ID of the prompt given to the model to generate slogans"
    )

    parser.add_argument(
        "--paper-ids", 
        nargs="+",
        type=str,
        required=False,
        default=[],
        help="List of paper IDs whose theorems get slogan-ified"
    )

    parser.add_argument(
        "--authors", 
        nargs="+",
        type=str,
        required=False,
        default=[],
        help="List of authors whose papers' theorems get slogan-ified"
    )

    parser.add_argument(
        "--min-citations",
        type=int,
        required=False,
        default=-1,
        help="Minimum amount of citations on a paper to slogan-ify its theorems"
    )

    parser.add_argument(
        "--in-journal",
        action="store_true",
        help="Whether to only slogan-ify theorems from papers found in a journal"
    )

    parser.add_argument(
        "-o",
        "--overwrite",
        action="store_true",
        help="Whether to overwrite existing slogans"
    )

    parser.add_argument(
        "--page-size",
        type=int,
        required=False,
        default=128,
        help="Size of each page of theorems to slogan-ify"
    )

    parser.add_argument(
        "--workers",
        type=int,
        required=False,
        default=16,
        help="Maximum number of workers to slogan-ify a page of theorems"
    )

    args = parser.parse_args()

    generate_slogans(
        model=args.model,
        prompt_id=args.prompt_id,
        paper_ids=args.paper_ids,
        authors=args.authors,
        min_citations=args.min_citations,
        in_journal=args.in_journal,
        overwrite=args.overwrite,
        page_size=args.page_size,
        workers=args.workers
    )