"""
Online LLM dependency extraction via notation prompts.

Each LLM call carries a batch of ``llm_batch_size`` statements (default 10);
the model returns one ``{defines, uses}`` entry per statement. Batches are
dispatched concurrently with a ThreadPoolExecutor.
"""
import itertools
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable, List

# itertools.count() is thread-safe in CPython, so multiple worker threads can
# share one counter to tag LLM calls with monotonic ids for --debug logs.
_call_seq = itertools.count(1)

from jinja2 import Environment, FileSystemLoader
from tqdm import tqdm

from rds.utils.query import build_query, get_query_count, sample_ids
from rds.utils.paginate import paginate_query
from .extract import parse_extraction_batch
from .write import _write_paper_deps, _fetch_paper_statements, _papers_already_processed

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _jinja_env():
    return Environment(
        loader=FileSystemLoader(_PROMPTS_DIR),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def _chunks(items: List, size: int) -> Iterable[List]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _llm_extract_batch(client, model_config: dict, template, statements: list,
                       debug: bool = False) -> dict:
    """One LLM call covering ``statements``. Returns a dict mapping each
    successfully-extracted ``statement_id`` to its ``{defines, uses}`` plus
    the call's token usage. Statements absent from ``extractions`` were not
    recovered (the model omitted or mangled them) and the caller counts them
    as failed.
    """
    prompt = template.render(statements=statements)
    # Per-statement token budget × batch size — the model gets proportionally
    # more output budget as we cram more statements into one call.
    per_stmt_max_tokens = model_config.get("max_tokens", 512)

    call_id = next(_call_seq)
    if debug:
        tqdm.write(f"[llm] #{call_id} → submit ({len(statements)} stmts, "
                   f"max_tokens={per_stmt_max_tokens * len(statements)})")
    t0 = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=model_config["id"],
            messages=[{"role": "user", "content": prompt}],
            temperature=model_config.get("temperature", 0.7),
            max_tokens=per_stmt_max_tokens * len(statements),
        )
    except Exception as e:
        if debug:
            tqdm.write(f"[llm] #{call_id} ✗ {time.perf_counter() - t0:.1f}s "
                       f"raised {type(e).__name__}: {e}")
        raise
    elapsed = time.perf_counter() - t0

    usage = response.usage
    extractions = parse_extraction_batch(
        response.choices[0].message.content.strip(),
        expected_ids=[str(s["statement_id"]) for s in statements],
    )
    if debug:
        in_t  = usage.prompt_tokens     if usage else 0
        out_t = usage.completion_tokens if usage else 0
        tqdm.write(f"[llm] #{call_id} ← {elapsed:.1f}s {in_t}→{out_t} tokens, "
                   f"got {len(extractions)}/{len(statements)} extractions")

    return {
        "extractions": extractions,
        "in_tokens":  usage.prompt_tokens     if usage else 0,
        "out_tokens": usage.completion_tokens if usage else 0,
    }


def _paper_query(condition, condition_params, shard, n_shards):
    base = (
        "SELECT paper.paper_id FROM paper"
        + (" LEFT JOIN arxiv_paper_metadata AS apm ON apm.arxiv_id = paper.external_id" if condition and "apm." in condition else "")
        + (" LEFT JOIN arxiv_parse_status AS aps ON aps.arxiv_id = paper.external_id" if condition and "aps." in condition else "")
    )
    return build_query(
        base_query=base,
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
            overwrite, batch_size, workers, shard, n_shards, sample=-1,
            llm_batch_size: int = 10, debug: bool = False):
    cost_per_1m_in  = model_config.get("cost_per_1m_in",  0.0)
    cost_per_1m_out = model_config.get("cost_per_1m_out", 0.0)

    query, params = _paper_query(condition, condition_params, shard, n_shards)
    if sample > 0:
        ids    = sample_ids(conn, query, params, sample)
        query  = "SELECT paper.paper_id FROM paper WHERE paper.paper_id = ANY(%s::uuid[])"
        params = [ids]
    total = get_query_count(conn, query, params)

    template = _jinja_env().get_template("notation.j2")
    # status is counted per statement (not per batch) so percentages remain
    # meaningful to a user thinking in statements.
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
            stmt_batches = list(_chunks(all_stmts, llm_batch_size))

            extracted_by_paper: dict = defaultdict(list)
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = {
                    ex.submit(_llm_extract_batch, client, model_config, template, batch, debug): batch
                    for batch in stmt_batches
                }
                for fut in as_completed(futures):
                    batch = futures[fut]
                    try:
                        result = fut.result()
                    except Exception as e:
                        status["failed"] += len(batch)
                        tqdm.write(f"[llm] batch of {len(batch)} failed: {e}")
                        continue

                    extractions = result["extractions"]
                    total_in  += result["in_tokens"]
                    total_out += result["out_tokens"]

                    n_missing = 0
                    for s in batch:
                        ex = extractions.get(str(s["statement_id"]))
                        if ex is None:
                            n_missing += 1
                            continue
                        extracted_by_paper[s["paper_id"]].append(
                            {**s, "defines": ex["defines"], "uses": ex["uses"]}
                        )
                    status["success"] += len(batch) - n_missing
                    status["failed"]  += n_missing
                    if n_missing:
                        tqdm.write(
                            f"[llm] {n_missing}/{len(batch)} statements missing from response"
                        )

            for pid in extracted_by_paper:
                all_ids = [s["statement_id"] for s in stmts_by_paper[pid]]
                extracted_by_paper[pid].sort(key=lambda s: s["ordinal"])
                _write_paper_deps(conn, all_ids, extracted_by_paper[pid])

            pbar.update(len(page))
            pbar.set_postfix({
                **_postfix(status, total_in, total_out, cost_per_1m_in, cost_per_1m_out),
                **({"skipped": status["skipped"]} if status["skipped"] else {}),
            })
