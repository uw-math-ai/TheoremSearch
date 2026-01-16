from tqdm import tqdm
from typing import List
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor, as_completed
from argparse import ArgumentParser
from .cost import format_USD
from .get_prompt import get_prompt
from .enums import Mode
from .generate_slogan import generate_slogan
from ..printing.scripts import print_script_header
from ..rds.query import build_query, get_query_count
from ..rds.connect import get_rds_connection
from ..rds.paginate import paginate_query
from ..rds.upsert import upsert_rows

def _update_pbar(pbar, sloganify_successes, sloganify_attempts, total_cost):
    sloganify_attempts += 1
    pbar.update(1)
    pbar.set_postfix({
        "gen_rate": f"{(100.0 * sloganify_successes / sloganify_attempts):.2f}%",
        "cost": format_USD(total_cost),
        "avg_cost": format_USD(total_cost / sloganify_successes) if sloganify_successes else "N/A"
    })

    return sloganify_attempts

def _generate_slogans(
    model_name: str,
    prompt_id: str,
    paper_ids: List[str],
    condition: str,
    condition_params: List[str],
    overwrite: bool,
    batch_size: int,
    workers: int,
    retries: int,
    use_langfuse: bool,
    mode: Mode
):
    if mode == Mode.DEBUGGING:
        use_langfuse = True
    if mode != Mode.PRODUCTION:
        workers = 0

    print_script_header(
        action="Generating slogans from the `theorem` table",
        params={
            "model_name": model_name,
            "prompt_id": prompt_id,
            "paper_ids?": paper_ids,
            "condition?": condition,
            "condition_params?": condition_params,
            "overwrite": overwrite,
            "batch_size": batch_size,
            "workers?": workers,
            "retries?": retries,
            "use_langfuse": use_langfuse,
            "mode": mode.name
        }
    )

    prompt = get_prompt(prompt_id)

    if paper_ids or any(c.startswith("paper.") for c in prompt["context"]):
        join_clause = "INNER JOIN paper ON theorem.paper_id = paper.paper_id"
    else:
        join_clause = ""

    select_cols = set([
        "theorem.theorem_id",
        *[f"{c} AS {c.replace('.', '__')}" for c in prompt["context"]]
    ])

    query, params = build_query(
        base_query=f"""
            SELECT {", ".join(select_cols)}
            FROM theorem
            {join_clause}
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
                "if": condition,
                "condition": condition,
                "params": condition_params
            }
        ]
    )

    conn = get_rds_connection()

    if mode == Mode.PRODUCTION:
        count = get_query_count(conn, query, params)

        sloganify_attempts = 0
        sloganify_successes = 0

        pbar = tqdm(total=count, dynamic_ncols=True)
        ex = ThreadPoolExecutor(max_workers=workers)
    else:
        pbar = nullcontext()
        ex = nullcontext()

    total_cost = 0.0

    with pbar, ex:
        for theorems in paginate_query(
            conn,
            base_query=query,
            base_params=params,
            order_by="theorem_id",
            descending=False,
            page_size=batch_size
        ):
            batch_slogan_rows = []

            if mode == Mode.PRODUCTION:
                fut_to_tid = {}

            for theorem in theorems:
                theorem_id = theorem["theorem_id"]
                context = {
                    c.replace("__" ,"."): theorem[c]
                    for c in theorem
                    if c != "theorem_id"
                }

                if mode == Mode.PRODUCTION:
                    fut = ex.submit(
                        generate_slogan,
                        model_name,
                        prompt,
                        theorem_id,
                        context,
                        retries,
                        use_langfuse,
                        mode
                    )
                    fut_to_tid[fut] = theorem_id
                else:
                    try:
                        slogan, cost = generate_slogan(
                            model_name,
                            prompt,
                            theorem_id,
                            context,
                            retries,
                            use_langfuse=use_langfuse,
                            mode=mode
                        )

                        if slogan.startswith("NOT POSSIBLE"):
                            raise ValueError(slogan)
                    except Exception as e:
                        print(f"[DEBUG] {theorem_id}: {e}")
                        continue

                    total_cost += cost

                    if slogan:
                        batch_slogan_rows.append({
                            "theorem_id": theorem_id,
                            "model": model_name,
                            "prompt_id": prompt_id,
                            "slogan": slogan,
                        })
            
            if mode == Mode.PRODUCTION:
                for fut in as_completed(fut_to_tid):
                    theorem_id = fut_to_tid[fut]

                    try:
                        slogan, cost = fut.result()
                    except Exception:
                        slogan = None
                        cost = 0

                    if slogan and not slogan.startswith("NOT POSSIBLE"):
                        sloganify_successes += 1
                        batch_slogan_rows.append({
                            "theorem_id": theorem_id,
                            "model": model_name,
                            "prompt_id": prompt_id,
                            "slogan": slogan,
                        })

                    total_cost += cost
                    sloganify_attempts = _update_pbar(pbar, sloganify_successes, sloganify_attempts, total_cost)

            if batch_slogan_rows:
                with conn.cursor() as cur:
                    upsert_rows(
                        cur,
                        table="theorem_slogan",
                        rows=batch_slogan_rows,
                        on_conflict={
                            "with": ["theorem_id", "model", "prompt_id"],
                            "replace": ["slogan"]
                        }
                    )

                if mode == Mode.PRODUCTION:
                    conn.commit()

    conn.close()

if __name__ == "__main__":
    arg_parser = ArgumentParser()

    arg_parser.add_argument(
        "--model",
        type=str,
        required=True,
        help="Name of LLM used to generate slogans"
    )

    arg_parser.add_argument(
        "--prompt-id",
        type=str,
        required=True,
        help="ID of prompt given to LLM to generate slogans"
    )

    arg_parser.add_argument(
        "--paper-ids",
        type=str,
        nargs="+",
        default=[],
        help="List of paper IDs to generate slogans for. By default, every paper"
    )

    arg_parser.add_argument(
        "--condition",
        type=str,
        nargs="+",
        default="",
        help="SQL condition to filter theorems followed by args"
    )

    arg_parser.add_argument(
        "-o", "--overwrite",
        action="store_true",
        help="Whether to overwrite previously generated slogans. By default, False"
    )

    arg_parser.add_argument(
        "--batch-size",
        type=int,
        default=128,
        help="The number of theorems in one batch. Also the number of theorems to attempt to sloganify concurrently in PRODUCTION mode"
    )

    arg_parser.add_argument(
        "--workers",
        type=int,
        default=16,
        help="Number of works used to sloganify each batch of theorems"
    )

    arg_parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Number of retries allowed if a slogan generation fails"
    )

    arg_parser.add_argument(
        "-lf", "--use-langfuse",
        action="store_true",
        help="Whether to use Langfuse. DEBUGGING mode always uses Langfuse, so this flag only affects PRODUCTION mode"
    )

    arg_parser.add_argument(
        "--mode",
        type=Mode,
        default=Mode.PRODUCTION,
        help="Mode to generate slogans in. By default, PRODUCTION"
    )

    args = arg_parser.parse_args()

    if args.condition and len(args.condition) >= 2:
        condition, *condition_params = args.condition
    else:
        condition = args.condition[0] if args.condition else None
        condition_params = []

    _generate_slogans(
        model_name=args.model,
        prompt_id=args.prompt_id,
        paper_ids=args.paper_ids,
        condition=condition,
        condition_params=condition_params,
        overwrite=args.overwrite,
        batch_size=args.batch_size,
        workers=args.workers,
        retries=args.retries,
        use_langfuse=args.use_langfuse,
        mode=args.mode
    )