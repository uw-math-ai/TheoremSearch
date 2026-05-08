import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import List, Dict, Optional
from tqdm import tqdm
from psycopg2.extensions import connection

from rds.utils.query import build_query, get_query_count
from rds.utils.paginate import paginate_query
from rds.utils.upsert import upsert_rows
from .llm_utils import proximity_score, proximity_keywords, max_anchor_strength, adjacent_keywords


def _overwrite_method_clause(do_deterministic: bool, do_heuristic: bool,
                              alias: str = "informal_dependency") -> str:
    m = []
    if do_deterministic: m.append("'deterministic'")
    if do_heuristic:     m.append("'heuristic'")
    return f" AND {alias}.methods && ARRAY[{', '.join(m)}]::text[]" if m else ""


def _reset_methods(cur, source_ids: list, do_deterministic: bool, do_heuristic: bool, intra: bool):
    cite_filter = "cite_key IS NULL" if intra else "cite_key IS NOT NULL"
    methods_to_remove = []
    if do_deterministic: methods_to_remove.append("deterministic")
    if do_heuristic:     methods_to_remove.append("heuristic")
    if not methods_to_remove:
        return
    arr = "ARRAY[" + ", ".join(f"'{m}'" for m in methods_to_remove) + "]::text[]"
    cur.execute(f"DELETE FROM informal_dependency WHERE {cite_filter} AND src_id = ANY(%s::uuid[]) AND methods <@ {arr}", (source_ids,))
    remove_expr = "methods"
    for m in methods_to_remove:
        remove_expr = f"array_remove({remove_expr}, '{m}')"
    cur.execute(f"UPDATE informal_dependency SET methods = {remove_expr} WHERE {cite_filter} AND src_id = ANY(%s::uuid[]) AND methods && {arr}", (source_ids,))


_REF_RE = re.compile(
    r'\\(?:[a-zA-Z]*[Rr]ef|autoref|cref|Cref|eqref)\*?\s*\{([^}]*)\}'
    r'|\\hyperref\*?\s*\[([^\]]*)\]'
)

_PROOF_START_RE = re.compile(
    r'^\s*(?:'
    r'\{\\(?:bf|it|textbf|textit)\s+Proof[\s.!]*\}'
    r'|\\(?:textbf|textit)\{Proof[^}]*\}'
    r'|\\begin\s*\{proof\}'
    r'|Proof\s*[.:\[]'
    r')',
    re.IGNORECASE,
)

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _truncate(text: Optional[str], max_chars: int, tail: bool = False) -> Optional[str]:
    if text and len(text) > max_chars:
        return ("…" + text[-max_chars:]) if tail else (text[:max_chars] + "…")
    return text


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
    stmt_order = {s["statement_id"]: i for i, s in enumerate(statements)}

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
                        dep_id = label_to_dep.get(label)
                        if dep_id and dep_id != statement["statement_id"] and label not in seen:
                            seen.add(label)
                            rows.append({
                                "src_id":   statement["statement_id"],
                                "location": location,
                                "cite_id":  None,
                                "cite_key": None,
                                "dep_id":   dep_id,
                                "dep_key":  label,
                                "dep_name": None,
                                "methods":  ["deterministic"],
                            })

    # ── Part 2: \ref in pre_context / post_context with proximity score ───
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
                        dep_id = label_to_dep.get(label)
                        if dep_id and dep_id != statement["statement_id"] and label not in seen:
                            if stmt_order.get(dep_id, -1) >= stmt_order[statement["statement_id"]]:
                                continue
                            seen.add(label)
                            dep_key = f"{label}|{kw}" if kw else f"{label}|"
                            rows.append({
                                "src_id":   statement["statement_id"],
                                "location": location,
                                "cite_id":  None,
                                "cite_key": None,
                                "dep_id":   dep_id,
                                "dep_key":  dep_key,
                                "dep_name": None,
                                "methods":  ["heuristic"],
                            })

    # ── Part 3: adjacent-statement deps via backward anchor in pre_context ─
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
                "methods":  ["heuristic"],
            })

    # ── Part 4: prose name matching ("Theorem 3.2" without any \ref) ─────
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
                    if stmt_order.get(dep_id, -1) >= stmt_order[statement["statement_id"]]:
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
                        "methods":  ["heuristic"],
                    })

    return rows


def connect_intrapaper_dependencies(
    conn: connection,
    condition: str,
    condition_params: List[str],
    batch_size: int,
    overwrite: bool,
    do_deterministic: bool,
    do_heuristic: bool = True,
    proximity_threshold: float = 0.5,
    shard: int = 0,
    n_shards: int = 1,
    sample: int = -1,
):
    query, params = build_query(
        base_query=(
            "SELECT paper_id FROM paper"
            + (" LEFT JOIN arxiv_paper_metadata AS apm ON apm.arxiv_id = paper.external_id" if condition and "apm." in condition else "")
            + (" LEFT JOIN arxiv_parse_status AS aps ON aps.arxiv_id = paper.external_id" if condition and "aps." in condition else "")
        ),
        sample=sample,
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
                    + _overwrite_method_clause(do_deterministic, do_heuristic)
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
    total_deps = 0

    with tqdm(total=count, dynamic_ncols=True, unit=" papers", desc="Intrapaper", file=sys.stdout) as pbar:
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
                batch_rows.extend(_process_paper_deterministic(
                    stmts,
                    run_pure=do_deterministic,
                    run_heuristic=do_heuristic,
                    proximity_threshold=proximity_threshold,
                ))

            total_deps += len(batch_rows)
            pbar.set_postfix({"deps": total_deps})

            if all_stmt_ids:
                source_ids = list(dict.fromkeys(all_stmt_ids))
                with conn.cursor() as cur:
                    _reset_methods(cur, source_ids, do_deterministic, do_heuristic, intra=True)
                if batch_rows:
                    upsert_rows(conn, table="informal_dependency", rows=batch_rows,
                                on_conflict={"with": ["src_id", "dep_id"],
                                             "where": "dep_id IS NOT NULL",
                                             "update_expr": "methods = ARRAY(SELECT DISTINCT unnest(informal_dependency.methods || EXCLUDED.methods))"})
                conn.commit()

            pbar.update(len(papers))
