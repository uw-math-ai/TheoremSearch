import re
import os
from pathlib import Path
from collections import defaultdict
from typing import Iterable, List, Dict, Optional, Tuple
from tqdm import tqdm
import yaml
from jinja2 import Environment, FileSystemLoader
from psycopg2.extensions import connection

from rds.utils.query import build_query, get_query_count
from rds.utils.paginate import paginate_query
from rds.utils.upsert import upsert_rows
from .llm_utils import build_stmt_id_map, parse_intra_llm_text, dedup_dep_rows, proximity_score, proximity_keywords, max_anchor_strength, adjacent_keywords

def _overwrite_method_clause(do_deterministic: bool, do_heuristic: bool, do_llm: bool, intra: bool) -> str:
    """Build the AND method IN (...) fragment for the not-overwrite skip condition."""
    m = []
    if do_deterministic: m += ["'deterministic'", "'deterministic+llm'"]
    if do_heuristic:     m += ["'heuristic'",     "'heuristic+llm'"]
    if do_llm:           m += ["'llm'",           "'deterministic+llm'", "'heuristic+llm'"]
    unique = list(dict.fromkeys(m))
    return f" AND informal_dependency.method IN ({', '.join(unique)})" if unique else ""


def _reset_methods(cur, source_ids: list, do_deterministic: bool, do_heuristic: bool, do_llm: bool, intra: bool):
    """Delete/reset rows that are about to be re-generated, preserving untouched halves."""
    cite_filter = "cite_key IS NULL" if intra else "cite_key IS NOT NULL"
    if do_deterministic and do_heuristic and do_llm:
        cur.execute(f"DELETE FROM informal_dependency WHERE {cite_filter} AND src_id = ANY(%s::uuid[])", (source_ids,))
        return
    base = []
    if do_deterministic: base.append("'deterministic'")
    if do_heuristic:     base.append("'heuristic'")
    if do_llm:           base.append("'llm'")
    if base:
        cur.execute(f"DELETE FROM informal_dependency WHERE {cite_filter} AND method IN ({', '.join(base)}) AND src_id = ANY(%s::uuid[])", (source_ids,))
    if do_deterministic and not do_llm:
        cur.execute(f"UPDATE informal_dependency SET method = 'llm' WHERE {cite_filter} AND method = 'deterministic+llm' AND src_id = ANY(%s::uuid[])", (source_ids,))
    if do_heuristic and not do_llm:
        cur.execute(f"UPDATE informal_dependency SET method = 'llm' WHERE {cite_filter} AND method = 'heuristic+llm' AND src_id = ANY(%s::uuid[])", (source_ids,))
    if do_llm and not do_deterministic:
        cur.execute(f"UPDATE informal_dependency SET method = 'deterministic' WHERE {cite_filter} AND method = 'deterministic+llm' AND src_id = ANY(%s::uuid[])", (source_ids,))
    if do_llm and not do_heuristic:
        cur.execute(f"UPDATE informal_dependency SET method = 'heuristic' WHERE {cite_filter} AND method = 'heuristic+llm' AND src_id = ANY(%s::uuid[])", (source_ids,))
    if do_deterministic and do_llm:
        cur.execute(f"DELETE FROM informal_dependency WHERE {cite_filter} AND method = 'deterministic+llm' AND src_id = ANY(%s::uuid[])", (source_ids,))
    if do_heuristic and do_llm:
        cur.execute(f"DELETE FROM informal_dependency WHERE {cite_filter} AND method = 'heuristic+llm' AND src_id = ANY(%s::uuid[])", (source_ids,))


_REF_RE = re.compile(
    r'\\(?:[a-zA-Z]*[Rr]ef|autoref|cref|Cref|eqref)\*?\s*\{([^}]*)\}'
    r'|\\hyperref\*?\s*\[([^\]]*)\]'
)

# Matches post_context that opens with an unparsed proof block.
_PROOF_START_RE = re.compile(
    r'^\s*(?:'
    r'\{\\(?:bf|it|textbf|textit)\s+Proof[\s.!]*\}'   # {\bf Proof.} / {\bf Proof .}
    r'|\\(?:textbf|textit)\{Proof[^}]*\}'              # \textbf{Proof...}
    r'|\\begin\s*\{proof\}'                             # \begin{proof}
    r'|Proof\s*[.:\[]'                                  # bare "Proof." / "Proof:"
    r')',
    re.IGNORECASE,
)

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_jinja_env = Environment(loader=FileSystemLoader(_PROMPTS_DIR), keep_trailing_newline=True)

def _render(template_name: str, **kwargs) -> str:
    return _jinja_env.get_template(template_name).render(**kwargs)

def _truncate(text: Optional[str], max_chars: int, tail: bool = False) -> Optional[str]:
    if text and len(text) > max_chars:
        return ("…" + text[-max_chars:]) if tail else (text[:max_chars] + "…")
    return text


def _make_stmt_id(stmt: dict, index: int) -> str:
    if stmt.get("ref"):
        return stmt["ref"]
    return f"{stmt['kind'].capitalize()} {index + 1}"


def _process_paper_deterministic(
    statements: list,
    run_pure: bool = True,
    run_heuristic: bool = True,
    proximity_threshold: float = 0.5,
) -> list:
    label_to_dep = {
        s["label"]: s["statement_id"]
        for s in statements
        if s["label"]
    }

    rows = []

    # ── Part 1: explicit \ref in body / note / proof ──────────────────────
    if run_pure and label_to_dep:
        for statement in statements:
            for location, text in [
                ("body",  statement["body"]),
                ("note",  statement["note"]),
                ("proof", statement["proof"]),
            ]:
                if not text:
                    continue
                seen: set = set()
                for m in _REF_RE.finditer(text):
                    content = m.group(1) or m.group(2)
                    if not content:
                        continue
                    for label in (lbl.strip() for lbl in content.split(',')):
                        if label in label_to_dep and label not in seen:
                            seen.add(label)
                            rows.append({
                                "src_id":   statement["statement_id"],
                                "location": location,
                                "cite_id":  None,
                                "cite_key": None,
                                "dep_id":   label_to_dep[label],
                                "dep_key":  label,
                                "dep_name": None,
                                "method":   "deterministic",
                            })

    # ── Part 2: \ref in pre_context / post_context with proximity score ───
    # For post_context that opens with a proof marker (proof wasn't parsed into
    # the proof field), all \refs are captured without a proximity requirement.
    if run_heuristic and label_to_dep:
        for statement in statements:
            for location, text in [
                ("pre_context",  statement.get("pre_context")),
                ("post_context", statement.get("post_context")),
            ]:
                if not text:
                    continue
                is_proof_context = (location == "post_context" and bool(_PROOF_START_RE.match(text)))
                seen = set()
                for m in _REF_RE.finditer(text):
                    if not is_proof_context and proximity_score(text, m.start()) < proximity_threshold:
                        continue
                    content = m.group(1) or m.group(2)
                    if not content:
                        continue
                    kw = "proof" if is_proof_context else proximity_keywords(text, m.start(), proximity_threshold)
                    for label in (lbl.strip() for lbl in content.split(',')):
                        if label in label_to_dep and label not in seen:
                            seen.add(label)
                            dep_key = f"{label}|{kw}" if kw else f"{label}|"
                            rows.append({
                                "src_id":   statement["statement_id"],
                                "location": location,
                                "cite_id":  None,
                                "cite_key": None,
                                "dep_id":   label_to_dep[label],
                                "dep_key":  dep_key,
                                "dep_name": None,
                                "method":   "heuristic",
                            })

    # ── Part 3: adjacent-statement deps via backward anchor in pre_context ─
    # Score is decayed by word count: longer pre_context = weaker signal.
    # Half-life = 30 words (score halved at 30 words).
    _ADJACENT_DECAY_HALFLIFE = 30.0
    if not run_heuristic:
        return rows
    for i in range(len(statements) - 1):
        stmt_a = statements[i]
        stmt_b = statements[i + 1]
        pre = stmt_b.get("pre_context") or ""
        n_words = len(pre.split()) if pre else 0
        score = max_anchor_strength(pre) / (1 + n_words / _ADJACENT_DECAY_HALFLIFE)
        if score >= proximity_threshold:
            rows.append({
                "src_id":   stmt_b["statement_id"],
                "location": "pre_context",
                "cite_id":  None,
                "cite_key": None,
                "dep_id":   stmt_a["statement_id"],
                "dep_key":  "|" + adjacent_keywords(pre, proximity_threshold),
                "dep_name": None,
                "method":   "heuristic",
            })

    # ── Part 4: prose name matching ("Theorem 3.2" without any \ref) ─────
    # Builds a lookup of "Kind Ref" → statement_id for every statement that
    # has a ref, then scans all text fields for exact matches.
    name_to_dep = {
        f"{s['kind'].capitalize()} {s['ref']}": s["statement_id"]
        for s in statements
        if s.get("ref") and s.get("kind")
    }
    if name_to_dep:
        _name_re = re.compile(
            r'\b(' + '|'.join(re.escape(n) for n in sorted(name_to_dep, key=len, reverse=True)) + r')\b'
        )
        for statement in statements:
            for location, text in [
                ("body",         statement["body"]),
                ("proof",        statement["proof"]),
                ("note",         statement["note"]),
                ("pre_context",  statement.get("pre_context")),
                ("post_context", statement.get("post_context")),
            ]:
                if not text:
                    continue
                seen: set = set()
                for m in _name_re.finditer(text):
                    name = m.group(1)
                    dep_id = name_to_dep[name]
                    if dep_id == statement["statement_id"] or name in seen:
                        continue
                    seen.add(name)
                    rows.append({
                        "src_id":   statement["statement_id"],
                        "location": location,
                        "cite_id":  None,
                        "cite_key": None,
                        "dep_id":   dep_id,
                        "dep_key":  name,
                        "dep_name": name,
                        "method":   "heuristic",
                    })

    return rows


def _process_paper_llm(statements: list, client, model: str, max_chars: int = 128) -> Tuple[list, int, int]:
    """Returns (rows, input_tokens, output_tokens)."""
    if len(statements) < 2:
        return [], 0, 0

    # Build a short human-readable id for each statement so the LLM can
    # refer to them naturally. Use ref ("Theorem 3.2") when available.
    id_to_statement_id: Dict[str, str] = {}
    stmt_items = []
    used_ids: Dict[str, int] = {}

    for i, s in enumerate(statements):
        base_id = _make_stmt_id(s, i)
        # Deduplicate in case two statements share the same ref
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

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _render("intrapaper_llm_system.j2")},
                {"role": "user",   "content": yaml.dump(stmt_items, allow_unicode=True, sort_keys=False)},
            ],
            max_tokens=16384,
            extra_body={"chat_template_kwargs": {"enable_thinking": True, "thinking_budget": 8000}},
        )
        usage = response.usage
        in_tokens  = getattr(usage, "prompt_tokens",     0) or 0
        out_tokens = getattr(usage, "completion_tokens", 0) or 0
        
        text = response.choices[0].message.content.strip()
    except Exception as e:
        tqdm.write(f"[intrapaper llm] error: {e}")
        return [], 0, 0

    rows = parse_intra_llm_text(text, id_to_statement_id)
    if rows is None:
        tqdm.write(f"[intrapaper llm] failed to parse response:\n{text[:500]}")
        return [], in_tokens, out_tokens

    return rows, in_tokens, out_tokens


def _merge(det_rows: list, llm_rows: list) -> list:
    """Merge deterministic/heuristic and LLM rows into one row per (src_id, dep_id).

    - Deduplicates each source by (src_id, dep_id), keeping best location.
    - Base method ("deterministic" or "heuristic") is preserved from det_rows;
      "+llm" is appended when the LLM independently found the same dep.
    - Location preference: body > proof > note > pre_context > post_context.
    """
    det_rows = dedup_dep_rows(det_rows)
    llm_rows = dedup_dep_rows(llm_rows)

    llm_keys = {(r["src_id"], r["dep_id"]) for r in llm_rows}

    merged = []
    det_keys = set()
    for r in det_rows:
        key = (r["src_id"], r["dep_id"])
        det_keys.add(key)
        base = r.get("method", "deterministic")
        method = f"{base}+llm" if key in llm_keys else base
        merged.append({**r, "method": method})

    for r in llm_rows:
        key = (r["src_id"], r["dep_id"])
        if key not in det_keys:
            merged.append({**r, "method": "llm"})

    return merged


def connect_intrapaper_dependencies(
    conn: connection,
    condition: str,
    condition_params: List[str],
    batch_size: int,
    overwrite: bool,
    do_deterministic: bool,
    do_heuristic: bool = True,
    do_llm: bool = False,
    model: Optional[str] = None,
    max_chars: int = 128,
    proximity_threshold: float = 0.5,
    shard: int = 0,
    n_shards: int = 1,
):
    llm_client = None
    if do_llm:
        from openai import OpenAI
        llm_client = OpenAI(
            api_key=os.environ["NEBIUS_API_KEY"],
            base_url="https://api.studio.nebius.ai/v1/",
        )

    query, params = build_query(
        base_query=(
            "SELECT paper_id FROM paper"
            + (" LEFT JOIN arxiv_paper_metadata AS apm ON apm.arxiv_id = paper.external_id" if condition and "apm." in condition else "")
            + (" LEFT JOIN arxiv_parse_status AS aps ON aps.arxiv_id = paper.external_id" if condition and "aps." in condition else "")
        ),
        where_clauses=[
            {
                "if": True,
                "condition": """
                    EXISTS (
                        SELECT 1 FROM statement
                        WHERE statement.paper_id = paper.paper_id
                    )
                """
            },
            {
                "if": not overwrite,
                "condition": (
                    "NOT EXISTS ("
                    " SELECT 1 FROM statement"
                    " JOIN informal_dependency ON informal_dependency.src_id = statement.statement_id"
                    " WHERE statement.paper_id = paper.paper_id"
                    " AND informal_dependency.cite_key IS NULL"
                    + _overwrite_method_clause(do_deterministic, do_heuristic, do_llm, intra=True)
                    + ")"
                ),
            },
            {
                "if": condition,
                "condition": condition,
                "params": condition_params,
            },
            {
                "if": n_shards > 1,
                "condition": "hashtext(paper_id::text) %% %s = %s",
                "params": [n_shards, shard],
            },
        ]
    )

    count = get_query_count(conn, query, params)

    total_in_tokens  = 0
    total_out_tokens = 0
    total_deps       = 0

    def _fmt_tokens(n: int) -> str:
        return f"{n/1000:.1f}k" if n >= 1000 else str(n)

    with tqdm(total=count, dynamic_ncols=True, unit=" papers", desc="Intrapaper") as pbar:
        for papers in paginate_query(
            conn,
            base_query=query,
            base_params=params,
            order_by="paper_id",
            page_size=batch_size,
        ):
            paper_ids = [p["paper_id"] for p in papers]

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

            batch_rows = []
            all_stmt_ids: List[str] = []
            for paper in papers:
                stmts = statements_by_paper[paper["paper_id"]]
                all_stmt_ids.extend(s["statement_id"] for s in stmts)
                det_rows = _process_paper_deterministic(stmts, run_pure=do_deterministic, run_heuristic=do_heuristic, proximity_threshold=proximity_threshold) if (do_deterministic or do_heuristic) else []
                if do_llm:
                    llm_rows, in_tok, out_tok = _process_paper_llm(stmts, llm_client, model, max_chars)
                    total_in_tokens  += in_tok
                    total_out_tokens += out_tok
                else:
                    llm_rows = []
                batch_rows.extend(_merge(det_rows, llm_rows))

            total_deps += len(batch_rows)
            postfix = {"deps": total_deps}
            if do_llm:
                postfix["in"]  = _fmt_tokens(total_in_tokens)
                postfix["out"] = _fmt_tokens(total_out_tokens)
            pbar.set_postfix(postfix)

            if all_stmt_ids:
                source_ids = list(dict.fromkeys(all_stmt_ids))
                with conn.cursor() as cur:
                    _reset_methods(cur, source_ids, do_deterministic, do_heuristic, do_llm, intra=True)
                if batch_rows:
                    upsert_rows(conn, table="informal_dependency", rows=batch_rows)
                with conn.cursor() as cur:
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
                conn.commit()

            pbar.update(len(papers))


# ------------------------------------------------------------------ #
# Batch connect entry point (shared with batch/connect.py)            #
# ------------------------------------------------------------------ #

def connect_intra_llm_results(
    conn: connection,
    results: Iterable[Tuple[str, str]],
    batch_size: int = 256,
) -> Dict[str, int]:
    """Write pre-computed LLM intra-paper results (arxiv_id, text) into the DB.

    Always overwrites existing LLM rows. Deterministic rows are never clobbered.
    """
    written = failed = 0
    pending_rows: List[Dict] = []
    pending_stmt_ids: List[str] = []
    papers_buffered = 0

    def _flush():
        nonlocal pending_rows, pending_stmt_ids, papers_buffered
        if not pending_stmt_ids:
            return
        src_ids = list(dict.fromkeys(pending_stmt_ids))
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM informal_dependency WHERE cite_key IS NULL AND method = 'llm' AND src_id = ANY(%s::uuid[])",
                (src_ids,),
            )
            cur.execute(
                "UPDATE informal_dependency SET method = 'deterministic' WHERE cite_key IS NULL AND method = 'deterministic+llm' AND src_id = ANY(%s::uuid[])",
                (src_ids,),
            )
            cur.execute(
                "UPDATE informal_dependency SET method = 'heuristic' WHERE cite_key IS NULL AND method = 'heuristic+llm' AND src_id = ANY(%s::uuid[])",
                (src_ids,),
            )
        if pending_rows:
            upsert_rows(conn, "informal_dependency", pending_rows)
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE informal_dependency d SET method = 'deterministic+llm'
                WHERE d.cite_key IS NULL AND d.method = 'deterministic'
                  AND d.src_id = ANY(%s::uuid[])
                  AND d.dep_id IS NOT NULL
                  AND EXISTS (
                      SELECT 1 FROM informal_dependency
                      WHERE src_id = d.src_id AND dep_id = d.dep_id AND method = 'llm'
                  )
            """, (src_ids,))
            cur.execute("""
                UPDATE informal_dependency d SET method = 'heuristic+llm'
                WHERE d.cite_key IS NULL AND d.method = 'heuristic'
                  AND d.src_id = ANY(%s::uuid[])
                  AND d.dep_id IS NOT NULL
                  AND EXISTS (
                      SELECT 1 FROM informal_dependency
                      WHERE src_id = d.src_id AND dep_id = d.dep_id AND method = 'llm'
                  )
            """, (src_ids,))
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
            """, (src_ids,))
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
            """, (src_ids, src_ids))
        conn.commit()
        pending_rows.clear()
        pending_stmt_ids.clear()
        papers_buffered = 0

    for arxiv_id, text in tqdm(results, unit=" papers", desc="Connecting intra", dynamic_ncols=True):
        with conn.cursor() as cur:
            cur.execute("""
                SELECT s.statement_id, s.kind, im.ref
                FROM statement s
                INNER JOIN informal_metadata im ON im.statement_id = s.statement_id
                INNER JOIN paper p ON p.paper_id = s.paper_id
                WHERE p.external_id = %s AND p.kind = 'paper'
            """, (arxiv_id,))
            statements = [
                {"statement_id": r[0], "kind": r[1], "ref": r[2]}
                for r in cur.fetchall()
            ]

        if not statements:
            tqdm.write(f"  Warning: no statements for {arxiv_id}, skipping.")
            failed += 1
            continue

        id_to_stmt = build_stmt_id_map(statements)
        rows = parse_intra_llm_text(text, id_to_stmt)
        if rows is None:
            tqdm.write(f"  Warning: failed to parse LLM response for {arxiv_id}.")
            failed += 1
            continue

        pending_rows.extend({**r, "method": "llm"} for r in rows)
        pending_stmt_ids.extend(s["statement_id"] for s in statements)
        written += len(rows)
        papers_buffered += 1

        if papers_buffered >= batch_size:
            _flush()

    _flush()
    return {"written": written, "failed": failed}
