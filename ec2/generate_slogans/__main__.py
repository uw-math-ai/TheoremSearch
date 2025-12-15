"""
Given theorem filters, generates slogans for all theorems in 'theorem' satisfying the filters
and uploads them to the 'theorem_slogan' table in the RDS.
"""

from ..rds.connect import get_rds_connection
from ..rds.upsert import upsert_rows
from ..rds.query import build_query
import argparse
from ..rds.paginate import paginate_query
import os
import json
from .slogans import generate_theorem_slogans
import boto3
from tqdm import tqdm
from .models import MODELS

def generate_slogans(
    model_name: str,
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

    model = MODELS[model_name]

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

    query, params = build_query(
        base_query=f"""
            SELECT {select_cols}
            FROM theorem
            INNER JOIN paper
                ON theorem.paper_id = paper.paper_id
        """,
        where_clauses=[
            {
                "if": not overwrite,
                "condition": """
                    NOT EXISTS (
                        SELECT 1
                        FROM theorem_slogan AS ts
                        WHERE ts.theorem_id = theorem.theorem_id
                            AND ts.model = %s
                            AND ts.prompt_id = %s
                    )
                """,
                "params": [model_name, prompt_id]
            },
            {
                "if": paper_ids,
                "condition": "paper.paper_id LIKE ANY(%s)",
                "param": ['%' + paper_id + '%' for paper_id in paper_ids]
            },
            {
                "if": authors,
                "condition": "paper.authors && %s",
                "param": authors
            },
            {
                "if": min_citations >= 0,
                "condition": "paper.citations >= %s",
                "param": min_citations
            },
            {
                "if": in_journal,
                "condition": "paper.journal_ref IS NOT NULL"
            }
        ]
    )

    count_query = f"""
        SELECT COUNT(*)
        FROM ({query}) AS q
    """

    with conn.cursor() as cur:
        cur.execute(count_query, (*params,))
        count = cur.fetchone()[0]

    script_announcement = f"=== Generating slogans for {count} theorems ==="
    print(script_announcement)
    print(f"  > model: {model_name}")
    print(f"  > prompt id: {prompt_id}")
    if paper_ids:
        print(f"  > paper ids: {paper_ids}")
    if authors:
        print(f"  > authors: {authors}")
    if min_citations is not None:
        print(f"  > citations: >= {min_citations}")
    if in_journal:
        print(f"  > in journal: True")
    print(f"  > overwrite: {overwrite}")
    print(f"  > page size: {page_size}")
    print(f"  > workers: {workers}")
    print("=" * len(script_announcement))

    n_theorems = 0

    brc = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION"))

    with tqdm(total=count, mininterval=0.1, smoothing=0.1, dynamic_ncols=True) as pbar:
        for theorem_contexts in paginate_query(
            conn,
            base_sql=query,
            base_params=(*params,),
            order_by="theorem_id",
            descending=False,
            page_size=page_size
        ):
            n_theorems += len(theorem_contexts)

            slogans = generate_theorem_slogans(
                brc,
                theorem_contexts,
                instructions=prompt["instructions"],
                temperature=prompt["temperature"],
                model=model,
                pbar=pbar,
                max_workers=workers
            )
            
            with conn.cursor() as cur:
                upsert_rows(
                    cur,
                    table="theorem_slogan",
                    rows=[
                        {
                            "theorem_id": theorem_context["theorem_id"],
                            "model": model_name,
                            "prompt_id": prompt_id,
                            "slogan": slogan
                        }
                        for slogan, theorem_context in zip(slogans, theorem_contexts)
                        if slogan is not None
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
        model_name=args.model,
        prompt_id=args.prompt_id,
        paper_ids=args.paper_ids,
        authors=args.authors,
        min_citations=args.min_citations,
        in_journal=args.in_journal,
        overwrite=args.overwrite,
        page_size=args.page_size,
        workers=args.workers
    )