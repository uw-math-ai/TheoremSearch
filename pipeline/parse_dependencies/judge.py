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

_SYSTEM_PROMPT        = (Path(__file__).parent / "prompts" / "intrapaper_judge_system.j2").read_text()
_VERIFY_SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "intrapaper_judge_verify_system.j2").read_text()

_VERIFY_BATCH_SIZE = 10


def _stmt_to_dict(stmt: dict) -> dict:
    name = stmt["kind"].capitalize()
    if stmt.get("ref"):
        name += f" {stmt['ref']}"
    obj: dict = {"statement_id": str(stmt["statement_id"]), "name": name}
    if stmt.get("label"):
        obj["label"] = stmt["label"]
    for field in ("body", "proof", "pre_context", "post_context"):
        obj[field] = stmt.get(field) or None
    return obj


def _paper_header(paper_info: dict) -> list:
    title    = paper_info.get("title",    "").strip()
    abstract = paper_info.get("abstract", "").strip()
    parts = [f"# Paper: \"{title}\""]
    if abstract:
        parts.append(f"**Abstract:** {abstract}")
    return parts


def _build_user_message(paper_info: dict, statements: list) -> str:
    sections = _paper_header(paper_info)
    sections.append("## Statements (document order)")
    sections.append(json.dumps([_stmt_to_dict(s) for s in statements], indent=2))
    return "\n\n".join(sections)


def _stmt_name(s: dict) -> str:
    return s["kind"].capitalize() + (f" {s['ref']}" if s.get("ref") else "")


def _build_verify_user_message(statements: list, deps: list) -> str:
    stmt_by_id = {str(s["statement_id"]): s for s in statements}

    cards = {}
    for i, d in enumerate(deps):
        src_id, dep_id = d["src"], d["dep"]
        location = d.get("location") or "body"

        if src_id in stmt_by_id:
            s = stmt_by_id[src_id]
            src_card: dict = {"order": s.get("ordinal"), "name": _stmt_name(s)}
            field_text = s.get(location)
            if field_text:
                src_card[location] = field_text
        else:
            src_card = {"statement_id": src_id}

        if dep_id in stmt_by_id:
            p = stmt_by_id[dep_id]
            dep_card: dict = {"order": p.get("ordinal"), "name": _stmt_name(p)}
            if p.get("body"):
                dep_card["body"] = p["body"]
            if p.get("note"):
                dep_card["note"] = p["note"]
        else:
            dep_card = {"statement_id": dep_id}

        entry: dict = {"src": src_card, "dep": dep_card, "location": location}
        if d.get("dep_key"):
            entry["dep_key"] = d["dep_key"]
        cards[str(i)] = entry

    return json.dumps(cards, indent=2)


def _call_judge(
    user: str,
    client,
    model_config: dict,
    system: Optional[str] = None,
) -> Tuple[Optional[str], int, int]:
    try:
        response = client.chat.completions.create(
            model=model_config["id"],
            messages=[
                {"role": "system", "content": system or _SYSTEM_PROMPT},
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


_VALID_LOCATIONS = {"body", "proof", "pre_context", "post_context"}


def _parse_verify_json(text: str, ordered_pairs: list) -> Optional[tuple]:
    try:
        data = json.loads(strip_code_fence(text.strip()))
        if not isinstance(data, dict):
            return None
    except Exception:
        return None
    approved = set()
    reasons: dict = {}
    for k, v in data.items():
        try:
            i = int(k)
        except (ValueError, TypeError):
            return None
        if not (0 <= i < len(ordered_pairs)):
            continue
        pair = ordered_pairs[i]
        if v is True:
            approved.add(pair)
        elif isinstance(v, dict):
            reasons[pair] = str(v.get("reason", "")).strip()
        elif v is False:
            reasons[pair] = ""
        else:
            return None
    return approved, reasons


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
    debug: bool = False,
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
                "if": sample > 0,
                "condition": (
                    "(SELECT COUNT(*) FROM statement s"
                    " JOIN informal_dependency d ON d.src_id = s.statement_id"
                    " WHERE s.paper_id = p.paper_id AND d.cite_key IS NULL AND d.dep_id IS NOT NULL) >= 10"
                ),
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
    total_endorsed = total_rejected = 0
    cost_per_1m_in  = model_config.get("cost_per_1m_in",  0.0)
    cost_per_1m_out = model_config.get("cost_per_1m_out", 0.0)

    def _total_cost():
        return total_in / 1e6 * cost_per_1m_in + total_out / 1e6 * cost_per_1m_out

    def _fmt_cost(c): return f"${c:.4f}"

    print(f"Judge: {count} paper(s) to process\n")

    paper_num = 0
    for papers in paginate_query(conn, base_query=query, base_params=params, order_by="paper_id", page_size=batch_size):
        for paper in papers:
            paper_num += 1
            paper_id   = paper["paper_id"]
            ext_id     = paper.get("external_id", "")
            title      = (paper["title"] or "").strip()
            title_disp = f'"{title[:72]}"' if title else "(no title)"
            print(f"[{paper_num}/{count}] {title_disp}  ({ext_id})")

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
                    SELECT s.statement_id, s.kind, im.ref, im.note, im.label,
                           s.body, s.proof, im.pre_context, im.post_context, im.ordinal
                    FROM statement s
                    JOIN informal_metadata im ON im.statement_id = s.statement_id
                    WHERE s.paper_id = %s
                    ORDER BY im.ordinal
                    """,
                    (paper_id,),
                )
                statements = [
                    dict(zip(["statement_id","kind","ref","note","label","body","proof","pre_context","post_context","ordinal"], r))
                    for r in cur.fetchall()
                ]

            if not statements:
                print("  (no statements — skipped)\n")
                continue

            # ── Phase 1: generate ─────────────────────────────────────────
            print(f"  Phase 1  generating...")
            valid_ids = {str(s["statement_id"]) for s in statements}
            user_msg  = _build_user_message(paper_info, statements)
            text, in_tok, out_tok = _call_judge(user_msg, client, model_config)
            total_in    += in_tok
            total_out   += out_tok
            papers_done += 1

            if text is None:
                print(f"  Phase 1  FAILED (API error) | cost so far: {_fmt_cost(_total_cost())}\n")
                failed += 1
                continue

            rows = _parse_judge_json(text, valid_ids)
            if rows is None:
                print(f"  Phase 1  FAILED (parse error) | cost so far: {_fmt_cost(_total_cost())}\n")
                failed += 1
                continue

            stmt_ids = [s["statement_id"] for s in statements]
            with conn.cursor() as cur:
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

            merged = len(rows) - len(new_rows)
            print(f"  Phase 1  done — {len(rows)} deps  ({merged} merged, {len(new_rows)} new) | cost so far: {_fmt_cost(_total_cost())}")
            total_deps += len(rows)

            # ── Phase 2: verify ───────────────────────────────────────────
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT src_id::text, dep_id::text, dep_key, location"
                    " FROM informal_dependency"
                    " WHERE cite_key IS NULL AND dep_id IS NOT NULL"
                    " AND NOT ('judge' = ANY(methods))"
                    " AND src_id = ANY(%s::uuid[])",
                    (stmt_ids,),
                )
                existing = cur.fetchall()

            if existing:
                ordered_pairs  = [(r[0], r[1]) for r in existing]
                deps_to_review = [{"src": r[0], "dep": r[1], "dep_key": r[2], "location": r[3]} for r in existing]
                paper_endorsed = paper_rejected = 0

                stmt_name = {
                    str(s["statement_id"]): (s["kind"].capitalize() + (f" {s['ref']}" if s.get("ref") else ""))
                    for s in statements
                }

                with tqdm(total=len(existing), desc="  Phase 2", unit=" deps",
                          dynamic_ncols=True, file=sys.stdout) as vbar:
                    for batch_start in range(0, len(deps_to_review), _VERIFY_BATCH_SIZE):
                        batch_deps  = deps_to_review[batch_start:batch_start + _VERIFY_BATCH_SIZE]
                        batch_pairs = ordered_pairs[batch_start:batch_start + _VERIFY_BATCH_SIZE]

                        verify_msg  = _build_verify_user_message(statements, batch_deps)
                        verify_text, v_in, v_out = _call_judge(verify_msg, client, model_config, system=_VERIFY_SYSTEM_PROMPT)
                        total_in  += v_in
                        total_out += v_out

                        if verify_text is None:
                            vbar.update(len(batch_deps))
                            continue
                        result = _parse_verify_json(verify_text, batch_pairs)
                        if result is None:
                            tqdm.write(f"  [batch {batch_start}] parse error: {verify_text[:100]!r}")
                            vbar.update(len(batch_deps))
                            continue
                        approved, reasons = result

                        with conn.cursor() as cur:
                            for src_id, dep_id in approved:
                                cur.execute(
                                    "UPDATE informal_dependency"
                                    " SET methods = array_append(methods, 'judge')"
                                    " WHERE src_id = %s::uuid AND dep_id = %s::uuid AND cite_key IS NULL",
                                    (src_id, dep_id),
                                )
                        if debug:
                            for (src_id, dep_id), reason in reasons.items():
                                src_name = stmt_name.get(src_id, src_id)
                                dep_name = stmt_name.get(dep_id, dep_id)
                                tqdm.write(f"    [rejected] {src_name} → {dep_name}: {reason or '(no reason)'}")
                        batch_rejected  = len(batch_pairs) - len(approved)
                        paper_endorsed += len(approved)
                        paper_rejected += batch_rejected
                        total_endorsed += len(approved)
                        total_rejected += batch_rejected
                        vbar.update(len(batch_deps))
                        vbar.set_postfix({"endorsed": paper_endorsed, "withheld": paper_rejected,
                                          "cost": _fmt_cost(_total_cost())})

                print(f"  Phase 2  done — {paper_endorsed} endorsed, {paper_rejected} withheld")

            conn.commit()
            print()

    print(f"Done.  {papers_done} papers | {total_deps} generated | "
          f"{total_endorsed} endorsed | {total_rejected} withheld | "
          f"{failed} failed | total cost: {_fmt_cost(_total_cost())}")
