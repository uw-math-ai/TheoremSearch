"""
Generates JSONL prompt batch files for generating theorem slogans at scale.
"""

from ....rds.connect import get_rds_connection
from ....rds.query import build_query, get_query_count
from ....rds.paginate import paginate_query
import os
from typing import Dict, List
import json
from tqdm import tqdm
import io
import boto3
import uuid
from argparse import ArgumentParser

s3 = boto3.client("s3")

S3_BUCKET = "proj-theorems"
S3_DIR = "batched_slogans"

def _get_prompt(prompt_id: str) -> Dict:
    parent_dir = os.path.normpath(
        os.path.join(
            os.path.dirname(__file__), 
            "..", "..", ".."
        )
    )

    path_to_prompt = os.path.join(
        parent_dir,
        "slogan_prompts",
        prompt_id + ".prompt"
    )

    try:
        with open(path_to_prompt, "r") as prompt_file:
            prompt = json.loads(prompt_file.read())

            prompt["instructions"] = " ".join(prompt["instructions"])
            prompt["context"] = [c + " AS " + c.replace(".", "_") for c in prompt["context"]]

            return prompt
    except Exception as e:
        raise ValueError(f"Error getting prompt '{prompt_id}'")

def _upload_jsonl(
    records: List[Dict],
    bucket: str,
    key: str
):
    buf = io.BytesIO()

    for obj in records:
        line = json.dumps(obj, separators=(",", ":"))
        buf.write(line.encode("utf-8"))
        buf.write(b"\n")

    buf.seek(0)

    s3.upload_fileobj(
        buf,
        bucket,
        key,
        ExtraArgs={"ContentType": "application/json"}
    )

def _get_key(id: uuid.UUID, page_index: int, total_pages: int) -> str:
    total_digits = len(str(total_pages))
    curr_digits = len(str(page_index))

    return f"{S3_DIR}/{id}/in/part-" + "0" * (total_digits - curr_digits) + str(page_index) + ".jsonl"

def build_batch_prompts(
    model_name: str,
    prompt_id: str,
    in_journal: bool,
    condition: str,
    overwrite: bool,
    page_size: int
):
    id = uuid.uuid1()
    conn = get_rds_connection()

    prompt = _get_prompt(prompt_id)
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
                "if": in_journal,
                "condition": "paper.journal_ref IS NOT NULL"
            },
            {
                "if": len(condition) > 0,
                "condition": condition
            }
        ]
    )

    count = get_query_count(conn, query, params)
    total_pages = count // page_size

    with tqdm(total=count, dynamic_ncols=True) as pbar:
        for page_index, theorem_contexts in enumerate(paginate_query(
            conn,
            base_sql=query,
            base_params=(*params,),
            order_by="theorem_id",
            descending=False,
            page_size=page_size
        )):
            prompt_batch = []

            for theorem_context in theorem_contexts:
                theorem_context = theorem_context.copy()
                theorem_id = theorem_context.pop("theorem_id")

                messages = [
                    {"role": "user", "content": prompt["instructions"]},
                    {"role": "user", "content": json.dumps(theorem_context)}
                ]
                payload = {"messages": messages, "max_tokens": 1024, "temperature": prompt["temperature"]}
                
                prompt_batch.append({
                    "recordId": theorem_id,
                    "modelInput": json.dumps(payload)
                })

            _upload_jsonl(
                prompt_batch, 
                bucket=S3_BUCKET,
                key=_get_key(id, page_index, total_pages)
            )

            pbar.update(len(theorem_contexts))


    conn.close()

    return f"{S3_BUCKET}/{S3_DIR}/{id}"

if __name__ == "__main__":
    arg_parser = ArgumentParser()

    arg_parser.add_argument(
        "--model",
        type=str,
        required=True
    )

    arg_parser.add_argument(
        "--prompt-id",
        type=str,
        required=True
    )

    arg_parser.add_argument(
        "-j",
        "--in-journal",
        action="store_true"
    )

    arg_parser.add_argument(
        "--condition",
        type=str,
        default=""
    )

    arg_parser.add_argument(
        "-o",
        "--overwrite",
        action="store_true",
    )

    arg_parser.add_argument(
        "--page-size",
        type=int,
        default=10_000
    )

    args = arg_parser.parse_args()

    s3_dir = build_batch_prompts(
        model_name=args.model, 
        prompt_id=args.prompt_id, 
        in_journal=args.in_journal,
        condition=args.condition, 
        overwrite=args.overwrite, 
        page_size=args.page_size
    )

    print(f"Batched slogan prompts generated in '{s3_dir}'")