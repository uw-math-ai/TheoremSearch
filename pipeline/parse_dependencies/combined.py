"""Combined (single-call) LLM dependency parsing for intra- and inter-paper deps."""

import os
import re
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from tqdm import tqdm
import yaml
from jinja2 import Environment, FileSystemLoader
from psycopg2.extensions import connection

from rds.utils.query import build_query, get_query_count
from rds.utils.paginate import paginate_query
from rds.utils.upsert import upsert_rows
from .llm_utils import build_stmt_id_map, parse_combined_llm_text, dedup_dep_rows
from .interpaper import _build_rows

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_jinja_env = Environment(loader=FileSystemLoader(_PROMPTS_DIR), keep_trailing_newline=True)


def _render(template_name: str, **kwargs) -> str:
    return _jinja_env.get_template(template_name).render(**kwargs)


def _thinking_kwargs(model: str, budget: int) -> dict:
    """Return extra_body and max_tokens appropriate for the model's thinking API."""
    if "kimi" in model.lower() or "moonshot" in model.lower():
        extra = {"thinking": {"type": "enabled", "budget_tokens": budget} if budget > 0 else {"type": "disabled"}}
        return {"max_tokens": 32768, "extra_body": extra}
    else:
        extra = {"chat_template_kwargs": {"enable_thinking": budget > 0, "thinking_budget": budget}}
        return {"max_tokens": 8192, "extra_body": extra}


def _truncate(text: Optional[str], max_chars: int, tail: bool = False) -> Optional[str]:
    if text and len(text) > max_chars:
        return ("…" + text[-max_chars:]) if tail else (text[:max_chars] + "…")
    return text


def _process_paper_combined(
    statements: List[Dict],
    bib: Dict[str, Dict],
    client,
    model: str,
    max_chars: int = 128,
    thinking_budget: int = 0,
) -> Tuple[List[Dict], Dict[str, list], int, int]:
    """Run one combined LLM call. Returns (intra_rows, inter_statement_cites, in_tok, out_tok)."""
    if len(statements) < 2:
        return [], {}, 0, 0

    # Pre-filter bib to keys that appear in statement text
    all_text = " ".join(
        (s.get(f) or "")
        for s in statements
        for f in ("body", "proof", "note", "pre_context", "post_context")
    )
    bib_for_llm = [k for k in bib if k in all_text] if bib else []

    id_to_statement_id: Dict[str, str] = {}
    used_ids: Dict[str, int] = {}
    stmt_items = []

    for i, s in enumerate(statements):
        base_id = s.get("ref") or f"{s['kind'].capitalize()} {i + 1}"
        if base_id in used_ids:
            used_ids[base_id] += 1
            sid = f"{base_id} ({used_ids[base_id]})"
        else:
            used_ids[base_id] = 0
            sid = base_id
        id_to_statement_id[sid] = s["statement_id"]

        item: dict = {"id": sid, "kind": s["kind"]}
        for field in ("note", "body", "proof", "pre_context", "post_context"):
            val = _truncate(s.get(field), max_chars, tail=(field == "pre_context"))
            if val:
                item[field] = val
        stmt_items.append(item)

    user_payload: dict = {"statements": stmt_items}
    if bib_for_llm:
        user_payload["bibliography"] = bib_for_llm

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _render("combined_llm_system.j2")},
                {"role": "user",   "content": yaml.dump(user_payload, allow_unicode=True, sort_keys=False)},
            ],
            **_thinking_kwargs(model, thinking_budget),
        )
        usage = response.usage
        in_tokens   = getattr(usage, "prompt_tokens",     0) or 0
        out_tokens  = getattr(usage, "completion_tokens", 0) or 0
        details     = getattr(usage, "completion_tokens_details", None)
        think_tokens = getattr(details, "reasoning_tokens", None) if details else None
        choice = response.choices[0]
        resp_tokens = (out_tokens - think_tokens) if think_tokens is not None else out_tokens
        raw = choice.message.content
        think_match = re.search(r'<think>(.*?)</think>', raw, flags=re.DOTALL)
        embedded_think_chars = len(think_match.group(1)) if think_match else 0
        text = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
        tqdm.write(
            f"[combined llm] in={in_tokens} think={think_tokens or embedded_think_chars//4} resp={resp_tokens}"
            + (" TRUNCATED" if choice.finish_reason == "length" else "")
        )
    except Exception as e:
        tqdm.write(f"[combined llm] error: {e}")
        return [], {}, 0, 0

    result = parse_combined_llm_text(text, bib, id_to_statement_id)
    if result is None:
        tqdm.write(f"[combined llm] failed to parse response:\n{text[:500]}")
        return [], {}, in_tokens, out_tokens

    intra_rows, inter_statement_cites = result
    return intra_rows, inter_statement_cites, in_tokens, out_tokens


def connect_combined_llm_dependencies(
    conn: connection,
    condition: str,
    condition_params: List[str],
    overwrite: bool,
    batch_size: int,
    similarity_threshold: float,
    model: str,
    max_chars: int = 128,
    thinking_budget: int = 0,
    shard: int = 0,
    n_shards: int = 1,
):
    from openai import OpenAI
    llm_client = OpenAI(
        api_key=os.environ["NEBIUS_API_KEY"],
        base_url="https://api.studio.nebius.ai/v1/",
    )

    query, params = build_query(
        base_query=(
            "SELECT p.paper_id, p.external_id"
            " FROM paper p"
            " LEFT JOIN arxiv_paper_metadata AS apm ON apm.arxiv_id = p.external_id"
            + (" LEFT JOIN arxiv_parse_status AS aps ON aps.arxiv_id = p.external_id" if condition and "aps." in condition else "")
        ),
        where_clauses=[
            {
                "if": True,
                "condition": "p.kind = 'paper'",
            },
            {
                "if": True,
                "condition": "EXISTS (SELECT 1 FROM statement s WHERE s.paper_id = p.paper_id)",
            },
            {
                "if": not overwrite,
                "condition": (
                    "NOT EXISTS ("
                    " SELECT 1 FROM statement s"
                    " JOIN informal_dependency d ON d.src_id = s.statement_id"
                    " WHERE s.paper_id = p.paper_id"
                    " AND d.method IN ('llm', 'deterministic+llm')"
                    ")"
                ),
            },
            {
                "if": condition,
                "condition": condition,
                "params": condition_params,
            },
            {
                "if": n_shards > 1,
                "condition": "hashtext(p.paper_id::text) %% %s = %s",
                "params": [n_shards, shard],
            },
        ]
    )

    count = get_query_count(conn, query, params)

    total_in_tokens  = 0
    total_out_tokens = 0

    def _fmt_tokens(n: int) -> str:
        return f"{n/1000:.1f}k" if n >= 1000 else str(n)

    with tqdm(total=count, dynamic_ncols=True, unit=" papers", desc="Combined LLM") as pbar:
        for papers in paginate_query(
            conn,
            base_query=query,
            base_params=params,
            order_by="paper_id",
            page_size=batch_size,
        ):
            paper_ids    = [p["paper_id"]   for p in papers]
            arxiv_id_map = {p["paper_id"]: p["external_id"] for p in papers}

            # Fetch all statements for the batch
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT s.statement_id, s.paper_id, s.kind, im.ref, im.label,
                           im.note, s.body, s.proof, im.pre_context, im.post_context
                    FROM statement s
                    INNER JOIN informal_metadata im ON im.statement_id = s.statement_id
                    WHERE s.paper_id = ANY(%s::uuid[])
                    ORDER BY s.paper_id, im.ordinal
                    """,
                    (paper_ids,)
                )
                batch_statements = [
                    dict(zip([
                        "statement_id", "paper_id", "kind", "ref", "label",
                        "note", "body", "proof", "pre_context", "post_context"
                    ], row))
                    for row in cur.fetchall()
                ]

            statements_by_paper: Dict[str, list] = defaultdict(list)
            for s in batch_statements:
                statements_by_paper[s["paper_id"]].append(s)

            all_intra_rows: List[Dict] = []
            all_inter_rows: List[Dict] = []
            all_stmt_ids:   List[str]  = []

            for paper in papers:
                pid      = paper["paper_id"]
                arxiv_id = arxiv_id_map[pid]
                stmts    = statements_by_paper[pid]
                all_stmt_ids.extend(s["statement_id"] for s in stmts)

                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT bibliography, bibtex FROM arxiv_paper_metadata WHERE arxiv_id = %s",
                            (arxiv_id,),
                        )
                        row = cur.fetchone()
                    bib: Dict[str, Dict] = (row[0] or {}) if row else {}
                    bibtex: bool = bool(row[1]) if row else True

                    intra_rows, inter_cites, in_tok, out_tok = _process_paper_combined(
                        stmts, bib, llm_client, model, max_chars, thinking_budget
                    )
                    total_in_tokens  += in_tok
                    total_out_tokens += out_tok

                    all_intra_rows.extend({**r, "method": "llm"} for r in intra_rows)

                    if inter_cites:
                        inter_rows = _build_rows(
                            conn, bib, inter_cites, similarity_threshold, bibtex=bibtex
                        )
                        all_inter_rows.extend({**r, "method": "llm"} for r in inter_rows)

                except Exception:
                    tqdm.write(f"[combined llm] skipping {arxiv_id}:\n{traceback.format_exc()}")

            pbar.set_postfix({
                "in":  _fmt_tokens(total_in_tokens),
                "out": _fmt_tokens(total_out_tokens),
            })

            if all_stmt_ids:
                source_ids = list(dict.fromkeys(all_stmt_ids))

                with conn.cursor() as cur:
                    # Reset intra LLM rows
                    cur.execute(
                        "DELETE FROM informal_dependency WHERE cite_key IS NULL AND method = 'llm' AND src_id = ANY(%s::uuid[])",
                        (source_ids,),
                    )
                    cur.execute(
                        "UPDATE informal_dependency SET method = 'deterministic' WHERE cite_key IS NULL AND method = 'deterministic+llm' AND src_id = ANY(%s::uuid[])",
                        (source_ids,),
                    )
                    cur.execute(
                        "UPDATE informal_dependency SET method = 'heuristic' WHERE cite_key IS NULL AND method = 'heuristic+llm' AND src_id = ANY(%s::uuid[])",
                        (source_ids,),
                    )
                    # Reset inter LLM rows
                    cur.execute(
                        "DELETE FROM informal_dependency WHERE cite_key IS NOT NULL AND method = 'llm' AND src_id = ANY(%s::uuid[])",
                        (source_ids,),
                    )
                    cur.execute(
                        "UPDATE informal_dependency SET method = 'deterministic' WHERE cite_key IS NOT NULL AND method = 'deterministic+llm' AND src_id = ANY(%s::uuid[])",
                        (source_ids,),
                    )
                    cur.execute(
                        "UPDATE informal_dependency SET method = 'heuristic' WHERE cite_key IS NOT NULL AND method = 'heuristic+llm' AND src_id = ANY(%s::uuid[])",
                        (source_ids,),
                    )

                if all_intra_rows or all_inter_rows:
                    upsert_rows(conn, table="informal_dependency", rows=all_intra_rows + all_inter_rows)

                with conn.cursor() as cur:
                    # Upgrade intra det/heuristic → det+llm/heuristic+llm where llm counterpart exists
                    cur.execute("""
                        UPDATE informal_dependency d SET method = 'deterministic+llm'
                        WHERE d.cite_key IS NULL AND d.method = 'deterministic'
                          AND d.src_id = ANY(%s::uuid[])
                          AND d.dep_id IS NOT NULL
                          AND EXISTS (
                              SELECT 1 FROM informal_dependency
                              WHERE src_id = d.src_id AND dep_id = d.dep_id AND method = 'llm'
                          )
                    """, (source_ids,))
                    cur.execute("""
                        UPDATE informal_dependency d SET method = 'heuristic+llm'
                        WHERE d.cite_key IS NULL AND d.method = 'heuristic'
                          AND d.src_id = ANY(%s::uuid[])
                          AND d.dep_id IS NOT NULL
                          AND EXISTS (
                              SELECT 1 FROM informal_dependency
                              WHERE src_id = d.src_id AND dep_id = d.dep_id AND method = 'llm'
                          )
                    """, (source_ids,))
                    cur.execute("""
                        DELETE FROM informal_dependency d
                        WHERE d.cite_key IS NULL AND d.method = 'llm'
                          AND d.src_id = ANY(%s::uuid[])
                          AND d.dep_id IS NOT NULL
                          AND EXISTS (
                              SELECT 1 FROM informal_dependency
                              WHERE src_id = d.src_id AND dep_id = d.dep_id
                                AND method IN ('deterministic+llm', 'heuristic+llm')
                          )
                    """, (source_ids,))
                    # Dedup intra
                    cur.execute("""
                        DELETE FROM informal_dependency
                        WHERE cite_key IS NULL
                          AND src_id = ANY(%s::uuid[])
                          AND ctid NOT IN (
                              SELECT DISTINCT ON (src_id, dep_id) ctid
                              FROM informal_dependency
                              WHERE cite_key IS NULL AND src_id = ANY(%s::uuid[])
                              ORDER BY src_id, dep_id,
                                  CASE method
                                      WHEN 'deterministic+llm' THEN 1
                                      WHEN 'deterministic'     THEN 2
                                      WHEN 'heuristic+llm'     THEN 3
                                      WHEN 'heuristic'         THEN 4
                                      ELSE 5
                                  END,
                                  CASE location
                                      WHEN 'body'         THEN 1
                                      WHEN 'proof'        THEN 2
                                      WHEN 'note'         THEN 3
                                      WHEN 'pre_context'  THEN 4
                                      ELSE 5
                                  END
                          )
                    """, (source_ids, source_ids))
                    # Upgrade inter det/heuristic → det+llm/heuristic+llm
                    cur.execute("""
                        UPDATE informal_dependency d SET method = 'deterministic+llm'
                        WHERE d.cite_key IS NOT NULL AND d.method = 'deterministic'
                          AND d.src_id = ANY(%s::uuid[])
                          AND EXISTS (
                              SELECT 1 FROM informal_dependency
                              WHERE src_id = d.src_id AND cite_key = d.cite_key AND method = 'llm'
                          )
                    """, (source_ids,))
                    cur.execute("""
                        UPDATE informal_dependency d SET method = 'heuristic+llm'
                        WHERE d.cite_key IS NOT NULL AND d.method = 'heuristic'
                          AND d.src_id = ANY(%s::uuid[])
                          AND EXISTS (
                              SELECT 1 FROM informal_dependency
                              WHERE src_id = d.src_id AND cite_key = d.cite_key AND method = 'llm'
                          )
                    """, (source_ids,))

                conn.commit()

            pbar.update(len(papers))
