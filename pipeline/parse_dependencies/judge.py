import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from tqdm import tqdm
from psycopg2.extensions import connection

from rds.utils.query import build_query, get_query_count
from rds.utils.paginate import paginate_query
from rds.utils.upsert import upsert_rows
from .llm_utils import strip_code_fence
from .models import load_model_config, build_openai_client

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

_SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "intrapaper_judge_system.j2").read_text()


def _fmt_stmt(stmt: dict) -> str:
    parts = [f"### {stmt['statement_id']}"]
    kind_line = stmt["kind"].capitalize()
    if stmt.get("ref"):
        kind_line += f" {stmt['ref']}"
    if stmt.get("note"):
        kind_line += f' — "{stmt["note"]}"'
    parts.append(f"*{kind_line}*\n")
    if stmt.get("body"):
        parts.append(f"**Statement:** {stmt['body']}")
    if stmt.get("proof"):
        parts.append(f"**Proof:** {stmt['proof']}")
    if stmt.get("pre_context"):
        parts.append(f"**Preceding text:** {stmt['pre_context']}")
    if stmt.get("post_context"):
        parts.append(f"**Following text:** {stmt['post_context']}")
    return "\n\n".join(parts)


def _build_user_message(paper_info: dict, statements: list) -> str:
    sections = []

    title = paper_info.get("title", "").strip()
    abstract = paper_info.get("abstract", "").strip()
    sections.append(f"# Paper: \"{title}\"")
    if abstract:
        sections.append(f"**Abstract:** {abstract}")

    sections.append("## Statements (document order)\n")
    for stmt in statements:
        sections.append(_fmt_stmt(stmt))

    return "\n\n".join(sections)


def _call_judge(
    user: str,
    client,
    model_config: dict,
) -> Tuple[Optional[str], int, int]:
    try:
        response = client.chat.completions.create(
            model=model_config["id"],
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user},
            ],
            max_tokens=model_config.get("max_tokens", 16384),
        )
        usage         = response.usage
        in_tok        = getattr(usage, "prompt_tokens",     0) or 0
        out_tok       = getattr(usage, "completion_tokens", 0) or 0
        choice        = response.choices[0]
        finish_reason = choice.finish_reason
        if finish_reason not in ("stop", "finished"):
            tqdm.write(f"[judge] warning: finish_reason={finish_reason!r} (in={in_tok}, out={out_tok})")
        text = choice.message.content or ""
        text = _THINK_RE.sub("", text).strip()
        return text, in_tok, out_tok
    except Exception as e:
        tqdm.write(f"[judge] API error: {e}")
        return None, 0, 0


_VALID_LOCATIONS = {"body", "proof", "pre_context", "post_context", "note"}


def _parse_judge_json(text: str, valid_ids: set) -> Optional[List[dict]]:
    try:
        data = json.loads(strip_code_fence(text.strip()))
        if not isinstance(data, list):
            return None
    except Exception:
        return None

    rows = []
    seen = set()
    for entry in data:
        src_id = str(entry.get("src") or "").strip()
        dep_id = str(entry.get("dep") or "").strip()
        if src_id not in valid_ids or dep_id not in valid_ids or src_id == dep_id:
            continue
        key = (src_id, dep_id)
        if key in seen:
            continue
        seen.add(key)
        dep_key  = str(entry.get("dep_key") or "").strip() or None
        location = str(entry.get("location") or "").strip()
        if location not in _VALID_LOCATIONS:
            location = "body"
        rows.append({
            "src_id":   src_id,
            "location": location,
            "cite_id":  None,
            "cite_key": None,
            "dep_id":   dep_id,
            "dep_key":  dep_key,
            "dep_name": None,
            "methods":  ["judge"],
        })
    return rows


def connect_judge_dependencies(
    conn: connection,
    condition: Optional[str],
    condition_params: List[str],
    batch_size: int,
    overwrite: bool,
    model_name: str,
    shard: int = 0,
    n_shards: int = 1,
    sample: int = -1,
):
    model_config = load_model_config(model_name)
    client = build_openai_client()

    query, params = build_query(
        base_query=(
            "SELECT p.paper_id, p.title, p.external_id"
            " FROM paper p"
            " LEFT JOIN arxiv_paper_metadata apm ON apm.arxiv_id = p.external_id"
            + (" LEFT JOIN arxiv_parse_status aps ON aps.arxiv_id = p.external_id" if condition and "aps." in condition else "")
        ),
        sample=sample,
        where_clauses=[
            {
                "if": True,
                "condition": "EXISTS (SELECT 1 FROM statement WHERE statement.paper_id = p.paper_id)",
            },
            {
                "if": not overwrite,
                "condition": (
                    "NOT EXISTS ("
                    " SELECT 1 FROM statement s"
                    " JOIN informal_dependency d ON d.src_id = s.statement_id"
                    " WHERE s.paper_id = p.paper_id"
                    " AND d.cite_key IS NULL AND 'judge' = ANY(d.methods)"
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
        ],
    )

    count = get_query_count(conn, query, params)
    total_in = total_out = total_deps = failed = papers_done = 0
    cost_per_1m_in  = model_config.get("cost_per_1m_in",  0.0)
    cost_per_1m_out = model_config.get("cost_per_1m_out", 0.0)

    def _total_cost():
        return total_in / 1e6 * cost_per_1m_in + total_out / 1e6 * cost_per_1m_out

    def _fmt_cost(c): return f"${c:.4f}"

    with tqdm(total=count, dynamic_ncols=True, unit=" papers", desc="Judge", file=sys.stdout) as pbar:
        for papers in paginate_query(conn, base_query=query, base_params=params, order_by="paper_id", page_size=batch_size):
            for paper in papers:
                paper_id   = paper["paper_id"]
                paper_info = {"title": paper["title"] or ""}

                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT abstract FROM arxiv_paper_metadata WHERE arxiv_id = %s",
                        (paper["external_id"],),
                    )
                    row = cur.fetchone()
                    paper_info["abstract"] = (row[0] or "") if row else ""

                    cur.execute(
                        """
                        SELECT s.statement_id, s.kind, im.ref, im.note,
                               s.body, s.proof, im.pre_context, im.post_context
                        FROM statement s
                        JOIN informal_metadata im ON im.statement_id = s.statement_id
                        WHERE s.paper_id = %s
                        ORDER BY im.ordinal
                        """,
                        (paper_id,),
                    )
                    statements = [
                        dict(zip(["statement_id","kind","ref","note","body","proof","pre_context","post_context"], r))
                        for r in cur.fetchall()
                    ]

                if not statements:
                    pbar.update(1)
                    continue

                valid_ids = {str(s["statement_id"]) for s in statements}
                user_msg = _build_user_message(paper_info, statements)
                text, in_tok, out_tok = _call_judge(user_msg, client, model_config)
                total_in    += in_tok
                total_out   += out_tok
                papers_done += 1

                if text is None:
                    failed += 1
                    pbar.update(1)
                    pbar.set_postfix({"deps": total_deps, "failed": failed, "cost": _fmt_cost(_total_cost()), "avg": _fmt_cost(_total_cost() / papers_done)})
                    continue

                rows = _parse_judge_json(text, valid_ids)
                if rows is None:
                    tqdm.write(f"[judge] failed to parse response for {paper_id}:\n{text[:200]}")
                    failed += 1
                    pbar.update(1)
                    pbar.set_postfix({"deps": total_deps, "failed": failed, "cost": _fmt_cost(_total_cost()), "avg": _fmt_cost(_total_cost() / papers_done)})
                    continue

                stmt_ids = [s["statement_id"] for s in statements]
                with conn.cursor() as cur:
                    # Strip "judge" from all existing intrapaper deps for this paper,
                    # then remove any rows that become method-less.
                    cur.execute(
                        "UPDATE informal_dependency"
                        " SET methods = array_remove(methods, 'judge')"
                        " WHERE cite_key IS NULL AND src_id = ANY(%s::uuid[])",
                        (stmt_ids,),
                    )
                    cur.execute(
                        "DELETE FROM informal_dependency"
                        " WHERE cite_key IS NULL AND methods = '{}' AND src_id = ANY(%s::uuid[])",
                        (stmt_ids,),
                    )

                new_rows = []
                if rows:
                    with conn.cursor() as cur:
                        for row in rows:
                            cur.execute(
                                "SELECT 1 FROM informal_dependency"
                                " WHERE src_id = %s::uuid AND dep_id = %s::uuid AND cite_key IS NULL",
                                (row["src_id"], row["dep_id"]),
                            )
                            if cur.fetchone():
                                cur.execute(
                                    "UPDATE informal_dependency"
                                    " SET methods = array_append(methods, 'judge')"
                                    " WHERE src_id = %s::uuid AND dep_id = %s::uuid AND cite_key IS NULL",
                                    (row["src_id"], row["dep_id"]),
                                )
                            else:
                                new_rows.append(row)

                if new_rows:
                    upsert_rows(conn, "informal_dependency", new_rows,
                                on_conflict={"with": ["src_id", "dep_id"],
                                             "where": "dep_id IS NOT NULL"})
                conn.commit()

                total_deps += len(rows)
                pbar.update(1)
                pbar.set_postfix({"deps": total_deps, "failed": failed, "cost": _fmt_cost(_total_cost()), "avg": _fmt_cost(_total_cost() / papers_done)})
