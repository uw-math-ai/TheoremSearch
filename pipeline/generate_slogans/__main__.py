import os
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import List, Optional

from openai import OpenAI
from tqdm import tqdm

from rds.utils.connect import get_rds_connection
from rds.utils.query import build_query, get_query_count
from rds.utils.paginate import paginate_query
from rds.utils.upsert import upsert_rows
from ..printing import print_script_header
from .prompt_utils import (
    load_prompt, load_model_config,
    detect_needed_joins, fetch_contexts, render_prompt,
    register_prompt, register_model,
    PROMPTS_DIR,
)


def generate_slogans(
    prompt_name: str,
    model_name: str,
    condition: Optional[str],
    condition_params: List[str],
    overwrite: bool,
    batch_size: int,
    workers: int,
    shard: int,
    n_shards: int,
    test: bool = False,
):
    spec = load_prompt(prompt_name)
    model_config = load_model_config(model_name)

    joins = detect_needed_joins(spec.source)

    print_script_header(
        action="Generating slogans",
        params={
            "test mode?":        test or None,
            "prompt":            prompt_name,
            "model":             model_name,
            "condition?":        condition,
            "condition params?": condition_params,
            "overwrite":         overwrite,
            "batch size":        batch_size,
            "workers":           workers,
            "shard?":            f"{shard}/{n_shards}" if n_shards > 1 else None,
        }
    )

    base_query = (
        "SELECT statement.statement_id FROM statement"
        + (" JOIN paper ON paper.paper_id = statement.paper_id" if condition and "paper." in condition else "")
    )

    conn = get_rds_connection("v2")

    if test:
        test_query, test_params = build_query(
            base_query=base_query,
            where_clauses=[
                {
                    "if": bool(condition),
                    "condition": condition or "",
                    "params": condition_params,
                },
                {
                    "if": n_shards > 1,
                    "condition": "ABS(hashtext(statement.statement_id::text)) %% %s = %s",
                    "params": [n_shards, shard],
                },
            ],
        )
        page = next(iter(paginate_query(conn, base_query=test_query, base_params=test_params, order_by="statement_id", page_size=1)), [])
        if not page:
            print("No matching statements found.")
            return
        sid = str(page[0]["statement_id"])
        contexts = fetch_contexts(conn, [sid], joins)
        if sid not in contexts:
            print(f"Could not fetch context for statement {sid}.")
            return
        rendered = render_prompt(spec.template, contexts[sid])
        example_path = PROMPTS_DIR / f"{prompt_name}.example.txt"
        example_path.write_text(rendered + "\n")
        print(f"Written to {example_path}\n")
        print(rendered)
        return

    register_prompt(conn, spec)
    register_model(conn, model_name, model_config)

    client = OpenAI(
        api_key=os.environ["NEBIUS_API_KEY"],
        base_url="https://api.studio.nebius.ai/v1/",
    )

    query, params = build_query(
        base_query=base_query,
        where_clauses=[
            {
                "if": not overwrite,
                "condition": """
                    NOT EXISTS (
                        SELECT 1 FROM slogan
                        WHERE slogan.statement_id = statement.statement_id
                          AND slogan.prompt_name = %s
                          AND slogan.model_name = %s
                    )
                """,
                "params": [spec.name, model_name],
            },
            {
                "if": bool(condition),
                "condition": condition or "",
                "params": condition_params,
            },
            {
                "if": n_shards > 1,
                "condition": "ABS(hashtext(statement.statement_id::text)) %% %s = %s",
                "params": [n_shards, shard],
            },
        ],
    )

    total = get_query_count(conn, query, params)
    status_counts = {"success": 0, "failed": 0}

    def call_llm(statement_id: str, prompt_text: str) -> dict:
        response = client.chat.completions.create(
            model=model_config["model"],
            messages=[{"role": "user", "content": prompt_text}],
            temperature=model_config.get("temperature", 0.7),
            max_tokens=model_config.get("max_tokens", 512),
        )
        usage = response.usage
        return {
            "statement_id": statement_id,
            "prompt_name":  spec.name,
            "model_name":   model_name,
            "slogan":       response.choices[0].message.content.strip(),
            "in_tokens":    usage.prompt_tokens     if usage else None,
            "out_tokens":   usage.completion_tokens if usage else None,
            "created_at":   datetime.now(timezone.utc),
        }

    cost_per_1m_in  = model_config.get("cost_per_1m_in",  0.0)
    cost_per_1m_out = model_config.get("cost_per_1m_out", 0.0)
    total_in_tokens  = 0
    total_out_tokens = 0

    pbar = tqdm(total=total, dynamic_ncols=True)

    with pbar, ThreadPoolExecutor(max_workers=workers) as ex:
        for page in paginate_query(
            conn,
            base_query=query,
            base_params=params,
            order_by="statement_id",
            page_size=batch_size,
        ):
            statement_ids = [str(row["statement_id"]) for row in page]
            contexts = fetch_contexts(conn, statement_ids, joins)

            fut_to_sid = {}
            for sid in statement_ids:
                if sid not in contexts:
                    status_counts["failed"] += 1
                    pbar.update()
                    continue
                prompt_text = render_prompt(spec.template, contexts[sid])
                fut = ex.submit(call_llm, sid, prompt_text)
                fut_to_sid[fut] = sid

            batch_rows = []
            for fut in as_completed(fut_to_sid):
                try:
                    row = fut.result()
                    batch_rows.append(row)
                    status_counts["success"] += 1
                    total_in_tokens  += row["in_tokens"]  or 0
                    total_out_tokens += row["out_tokens"] or 0
                except Exception as e:
                    status_counts["failed"] += 1
                    print(f"\n[error] {fut_to_sid[fut]}: {e}")
                pbar.update()
                total_done = sum(status_counts.values())
                cost = (
                    total_in_tokens  / 1_000_000 * cost_per_1m_in
                    + total_out_tokens / 1_000_000 * cost_per_1m_out
                )
                pbar.set_postfix({
                    "success": f"{100.0 * status_counts['success'] / total_done:.1f}%",
                    "avg_cost": f"${cost / status_counts['success']:.5f}" if status_counts["success"] else "$0",
                    "cost": f"${cost:.4f}",
                })

            if batch_rows:
                upsert_rows(
                    conn,
                    table="slogan",
                    rows=batch_rows,
                    on_conflict={
                        "with":    ["statement_id", "prompt_name", "model_name"],
                        "replace": ["slogan", "in_tokens", "out_tokens"],
                        # created_at intentionally excluded: preserves original creation time
                    },
                )
                conn.commit()


if __name__ == "__main__":
    parser = ArgumentParser(
        description="Generate LLM slogans for mathematical statements."
    )

    parser.add_argument(
        "-p", "--prompt",
        type=str,
        required=True,
        dest="prompt_name",
        help="Name of the prompt folder inside pipeline/generate_slogans/prompts/.",
    )
    parser.add_argument(
        "-c", "--condition",
        type=str,
        nargs="+",
        metavar=("SQL", "PARAM"),
        help=(
            "SQL WHERE condition to filter statements, followed by any bind parameters. "
            "The 'statement' table and (if needed) 'paper' table are in scope. "
            "Example: -c \"paper.external_id = %%s\" 2301.00001"
        ),
    )
    parser.add_argument(
        "-o", "--overwrite",
        action="store_true",
        help="Re-generate slogans for statements that already have one for this prompt.",
    )
    parser.add_argument(
        "-b", "--batch-size",
        type=int,
        default=32,
        dest="batch_size",
        help="Statements fetched and processed per iteration. Default: 32.",
    )
    parser.add_argument(
        "-m", "--model",
        type=str,
        required=True,
        dest="model_name",
        help="Short model name from models.json (e.g. 'qwen3-235b').",
    )
    parser.add_argument(
        "-w", "--workers",
        type=int,
        default=4,
        help="Concurrent LLM requests. Default: 4.",
    )
    parser.add_argument(
        "--shard",
        type=int,
        default=0,
        help="0-based shard index for array jobs. Default: 0.",
    )
    parser.add_argument(
        "--n-shards",
        type=int,
        default=1,
        dest="n_shards",
        help="Total number of shards. Default: 1 (no sharding).",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help=(
            "Render the prompt for the first matching statement and write it to "
            "prompts/<prompt>/example.txt. No LLM call or DB write."
        ),
    )

    args = parser.parse_args()

    if args.condition and len(args.condition) >= 2:
        condition, *condition_params = args.condition
    else:
        condition = args.condition[0] if args.condition else None
        condition_params = []

    generate_slogans(
        prompt_name=args.prompt_name,
        model_name=args.model_name,
        condition=condition,
        condition_params=condition_params,
        overwrite=args.overwrite,
        batch_size=args.batch_size,
        workers=args.workers,
        shard=args.shard,
        n_shards=args.n_shards,
        test=args.test,
    )
