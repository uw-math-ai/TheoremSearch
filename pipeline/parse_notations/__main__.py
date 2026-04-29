import json
import os
from argparse import ArgumentParser
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List

from jinja2 import Environment, FileSystemLoader
from openai import OpenAI
from tqdm import tqdm

from rds.utils.connect import get_rds_connection
from rds.utils.query import build_query, get_query_count
from rds.utils.paginate import paginate_query
from ..printing import print_script_header
from .extract import parse_extraction
from .write import _write_paper_deps, _fetch_paper_statements, _papers_already_processed

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_MODELS_FILE = Path(__file__).parent / "models.json"


def _load_model_config(name: str) -> dict:
    with open(_MODELS_FILE) as f:
        models = json.load(f)
    if name not in models:
        raise ValueError(f"Model '{name}' not in models.json. Available: {list(models)}")
    return models[name]


def _jinja_env():
    return Environment(
        loader=FileSystemLoader(_PROMPTS_DIR),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def _llm_extract(client, model_config: dict, template, stmt: dict) -> dict:
    prompt = template.render(statement=stmt)
    response = client.chat.completions.create(
        model=model_config["model"],
        messages=[{"role": "user", "content": prompt}],
        temperature=model_config.get("temperature", 0.7),
        max_tokens=model_config.get("max_tokens", 512),
    )
    usage = response.usage
    extraction = parse_extraction(response.choices[0].message.content.strip())
    return {
        **stmt,
        "defines":    extraction["defines"],
        "uses":       extraction["uses"],
        "in_tokens":  usage.prompt_tokens     if usage else 0,
        "out_tokens": usage.completion_tokens if usage else 0,
    }


def _paper_query(condition, condition_params, shard, n_shards):
    return build_query(
        base_query="SELECT paper.paper_id FROM paper",
        where_clauses=[
            {"if": bool(condition), "condition": condition or "", "params": condition_params},
            {
                "if":        n_shards > 1,
                "condition": "ABS(hashtext(paper.paper_id::text)) %% %s = %s",
                "params":    [n_shards, shard],
            },
        ],
    )


def _postfix(status: dict, total_in: int, total_out: int,
             cost_per_1m_in: float, cost_per_1m_out: float) -> dict:
    done = status["success"] + status["failed"]
    cost = total_in / 1_000_000 * cost_per_1m_in + total_out / 1_000_000 * cost_per_1m_out
    return {
        "success":  f"{100 * status['success'] / done:.1f}%" if done else "—",
        "avg_cost": f"${cost / status['success']:.5f}"       if status["success"] else "$0",
        "cost":     f"${cost:.4f}",
    }


def run(conn, client, model_config, template,
        condition, condition_params, overwrite,
        batch_size, workers, shard, n_shards):
    cost_per_1m_in  = model_config.get("cost_per_1m_in",  0.0)
    cost_per_1m_out = model_config.get("cost_per_1m_out", 0.0)

    query, params = _paper_query(condition, condition_params, shard, n_shards)
    total = get_query_count(conn, query, params)

    status = {"success": 0, "failed": 0, "skipped": 0}
    total_in = total_out = 0

    with tqdm(total=total, dynamic_ncols=True, unit=" papers") as pbar:
        for page in paginate_query(conn, base_query=query, base_params=params,
                                   order_by="paper_id", page_size=batch_size):
            paper_ids = [str(p["paper_id"]) for p in page]

            if not overwrite:
                already_done = _papers_already_processed(conn, paper_ids)
                to_process = [pid for pid in paper_ids if pid not in already_done]
                status["skipped"] += len(paper_ids) - len(to_process)
                paper_ids = to_process

            if not paper_ids:
                pbar.update(len(page))
                pbar.set_postfix(_postfix(status, total_in, total_out,
                                          cost_per_1m_in, cost_per_1m_out))
                continue

            stmts_by_paper = _fetch_paper_statements(conn, paper_ids)
            all_stmts = [s for stmts in stmts_by_paper.values() for s in stmts]

            extracted_by_paper: dict = defaultdict(list)
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = {ex.submit(_llm_extract, client, model_config, template, s): s
                           for s in all_stmts}
                for fut in as_completed(futures):
                    try:
                        result = fut.result()
                        extracted_by_paper[result["paper_id"]].append(result)
                        total_in  += result["in_tokens"]
                        total_out += result["out_tokens"]
                        status["success"] += 1
                    except Exception as e:
                        status["failed"] += 1
                        print(f"\n[error] {futures[fut]['statement_id']}: {e}")

            for pid in extracted_by_paper:
                all_ids = [s["statement_id"] for s in stmts_by_paper[pid]]
                extracted_by_paper[pid].sort(key=lambda s: s["ordinal"])
                _write_paper_deps(conn, all_ids, extracted_by_paper[pid])

            pbar.update(len(page))
            pbar.set_postfix({
                **_postfix(status, total_in, total_out, cost_per_1m_in, cost_per_1m_out),
                **({"skipped": status["skipped"]} if status["skipped"] else {}),
            })


def main():
    parser = ArgumentParser(description="Online notation dep extraction: LLM + match + write in one pass.")
    parser.add_argument("-m", "--model", required=True, dest="model_name",
                        help="Short model name from models.json (e.g. qwen3-235b).")
    parser.add_argument("-c", "--condition", type=str, nargs="+", metavar=("SQL", "PARAM"),
                        help="SQL WHERE condition on paper, followed by bind params.")
    parser.add_argument("--overwrite", action="store_true",
                        help="Re-process papers that already have llm deps.")
    parser.add_argument("-b", "--batch-size", type=int, default=16, dest="batch_size",
                        help="Papers per page (default: 16).")
    parser.add_argument("-w", "--workers", type=int, default=8,
                        help="Concurrent LLM requests (default: 8).")
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--n-shards", type=int, default=1, dest="n_shards")

    args = parser.parse_args()

    if args.condition and len(args.condition) >= 2:
        condition, *condition_params = args.condition
    else:
        condition        = args.condition[0] if args.condition else None
        condition_params = []

    model_config = _load_model_config(args.model_name)

    print_script_header(
        action="Generating notation deps (online)",
        params={
            "model":      args.model_name,
            "condition?": condition,
            "params?":    condition_params or None,
            "overwrite":  args.overwrite,
            "batch size": args.batch_size,
            "workers":    args.workers,
            "shard?":     f"{args.shard}/{args.n_shards}" if args.n_shards > 1 else None,
        },
    )

    conn = get_rds_connection("v2")
    client = OpenAI(
        api_key=os.environ["NEBIUS_API_KEY"],
        base_url="https://api.studio.nebius.ai/v1/",
    )
    template = _jinja_env().get_template("notation.j2")

    run(conn, client, model_config, template,
        condition, condition_params, args.overwrite,
        args.batch_size, args.workers, args.shard, args.n_shards)


if __name__ == "__main__":
    main()
