"""
Online LLM dependency extraction via per-statement notation prompts.

For each statement, asks the LLM what it defines and uses; then match_paper()
turns those annotations into dependency rows written to informal_dependency.
"""
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from tqdm import tqdm

from rds.utils.query import build_query, get_query_count
from rds.utils.paginate import paginate_query
from .extract import parse_extraction
from .write import _write_paper_deps, _fetch_paper_statements, _papers_already_processed

_PROMPTS_DIR = Path(__file__).parent / "prompts"


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
        model=model_config["id"],
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


def _paper_query(condition, condition_params, shard, n_shards, sample=-1):
    return build_query(
        base_query="SELECT paper.paper_id FROM paper",
        sample=sample,
        where_clauses=[
            {
                "if":        True,
                "condition": "EXISTS (SELECT 1 FROM statement WHERE statement.paper_id = paper.paper_id)",
            },
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


def run_llm(conn, client, model_config, condition, condition_params,
            overwrite, batch_size, workers, shard, n_shards, sample=-1):
    cost_per_1m_in  = model_config.get("cost_per_1m_in",  0.0)
    cost_per_1m_out = model_config.get("cost_per_1m_out", 0.0)

    query, params = _paper_query(condition, condition_params, shard, n_shards, sample=sample)
    total = get_query_count(conn, query, params)

    template = _jinja_env().get_template("notation.j2")
    status = {"success": 0, "failed": 0, "skipped": 0}
    total_in = total_out = 0

    with tqdm(total=total, dynamic_ncols=True, unit=" papers", desc="LLM", file=sys.stdout) as pbar:
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
                        tqdm.write(f"[llm] {futures[fut]['statement_id']}: {e}")

            for pid in extracted_by_paper:
                all_ids = [s["statement_id"] for s in stmts_by_paper[pid]]
                extracted_by_paper[pid].sort(key=lambda s: s["ordinal"])
                _write_paper_deps(conn, all_ids, extracted_by_paper[pid])

            pbar.update(len(page))
            pbar.set_postfix({
                **_postfix(status, total_in, total_out, cost_per_1m_in, cost_per_1m_out),
                **({"skipped": status["skipped"]} if status["skipped"] else {}),
            })
