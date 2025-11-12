"""
Given theorem filters, generates slogans for all theorems in 'theorem' satisfying the filters
and uploads them to the 'theorem_slogan' table in the RDS.
"""

from ..rds.connect import get_rds_connection
import argparse
from ..rds.paginate import paginate_query
import os
import json
from .slogans import generate_theorem_slogans

# TODO: Add support for more filters (i.e. paper categories, paper name patterns, 
# theorem name patterns, etc.)

conn = get_rds_connection()

def generate_slogans(
    model: str,
    prompt_id: str,
    paper_ids: list[str] = [],
    authors: list[str] = [],
    overwrite: bool = False,
    page_size: int = 100,
    workers: int = 16
):
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
        where_conditions.append("paper.paper_id IN %s")
        base_params.append(paper_ids)

    if authors:
        where_conditions.append("paper.authors && %s")
        base_params.append(authors)

    if where_conditions:
        base_sql += " WHERE " + " AND ".join(where_conditions)
        count_sql += " WHERE " + " AND ".join(where_conditions)

    with conn.cursor() as cur:
        cur.execute(count_sql, (*base_params,))
        n_results = cur.fetchone()[0]

    print(f"Generating slogans for {n_results} matching theorems:")
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
        print(f" > Page {1 + page}: {n_theorems}/{n_results}")

        slogans = generate_theorem_slogans(
            theorem_contexts,
            instructions=prompt["instructions"],
            model=model,
            max_workers=workers
        )
        
        for slogan, theorem_context in zip(slogans, theorem_contexts):
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO theorem_slogan (theorem_id, model, prompt_id, slogan)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (theorem_id, model, prompt_id) DO UPDATE
                    SET
                        slogan = EXCLUDED.slogan
                """, (
                    theorem_context["theorem_id"],
                    model,
                    prompt_id,
                    slogan
                ))

        conn.commit()

        print("> Uploaded page to RDS")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--model",
        type=str,
        required=True
    )

    parser.add_argument(
        "--prompt-id",
        type=str,
        required=True
    )

    parser.add_argument(
        "--paper-ids", 
        nargs="+",
        type=str,
        required=False,
        default=[]
    )

    parser.add_argument(
        "--authors", 
        nargs="+",
        type=str,
        required=False,
        default=[]
    )

    parser.add_argument(
        "--overwrite",
        type=bool,
        required=False,
        default=False
    )

    parser.add_argument(
        "--page_size",
        type=int,
        required=False,
        default=100
    )

    parser.add_argument(
        "--workers",
        type=int,
        required=False,
        default=16
    )

    args = parser.parse_args()

    generate_slogans(
        model=args.model,
        prompt_id=args.prompt_id,
        paper_ids=args.paper_ids,
        authors=args.authors,
        overwrite=args.overwrite,
        page_size=args.page_size,
        workers=args.workers
    )