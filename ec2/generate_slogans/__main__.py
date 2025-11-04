"""
Given theorem filters, generates slogans for all theorems in 'theorem' satisfying the filters
and uploads them to the 'theorem_slogan' table in the RDS.
"""

from typing import Optional
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
    paper_id: Optional[str],
    model: str,
    prompt_id: str
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

    select_cols = ", ".join(set(["paper.paper_id", "theorem.theorem_id", *prompt["context"]]))

    for theorem_contexts in paginate_query(
        conn,
        base_sql=f"""
            SELECT {select_cols}
            FROM theorem
            INNER JOIN paper
            ON theorem.paper_id = paper.paper_id
            WHERE paper.paper_id = %s
        """,
        base_params=(paper_id,),
        order_by="theorem_id",
        descending=False
    ):
        slogans = generate_theorem_slogans(
            theorem_contexts,
            instructions=prompt["instructions"],
            model=model
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
                    theorem_context["theorem.theorem_id"],
                    model,
                    prompt_id,
                    slogan
                ))

        conn.commit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--paper-id", 
        type=str, 
        required=False,
        default=None
    )

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
        "--workers",
        type=int,
        required=False,
        default=16
    )

    args = parser.parse_args()

    generate_slogans(
        args.paper_id, 
        args.model,
        args.prompt_id
    )