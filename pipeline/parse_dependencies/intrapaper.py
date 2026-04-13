import re
import json
import os
from pathlib import Path
from collections import defaultdict
from typing import List, Dict, Optional
from tqdm import tqdm
from jinja2 import Environment, FileSystemLoader
from psycopg2.extensions import connection

from rds.utils.query import build_query, get_query_count
from rds.utils.paginate import paginate_query
from rds.utils.upsert import upsert_rows

_REF_RE = re.compile(
    r'\\(?:[a-zA-Z]*[Rr]ef|autoref|cref|Cref|eqref)\s*\{([^}]*)\}'
    r'|\\hyperref\s*\[([^\]]*)\]'
)

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_jinja_env = Environment(loader=FileSystemLoader(_PROMPTS_DIR), keep_trailing_newline=True)

def _render(template_name: str, **kwargs) -> str:
    return _jinja_env.get_template(template_name).render(**kwargs)

_FIELD_MAX_CHARS = 1000


def _truncate(text: Optional[str]) -> Optional[str]:
    if text and len(text) > _FIELD_MAX_CHARS:
        return text[:_FIELD_MAX_CHARS] + "…"
    return text


def _make_stmt_id(stmt: dict, index: int) -> str:
    if stmt.get("ref"):
        return stmt["ref"]
    return f"{stmt['kind'].capitalize()} {index + 1}"


def _process_paper_deterministic(statements: list) -> list:
    label_to_dep = {
        s["label"]: s["statement_id"]
        for s in statements
        if s["label"]
    }
    if not label_to_dep:
        return []

    rows = []
    for statement in statements:
        for location, text in [
            ("body",  statement["body"]),
            ("note",  statement["note"]),
            ("proof", statement["proof"]),
        ]:
            if not text:
                continue
            seen = set()
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
                            "cite_key": None,
                            "cite_id":  None,
                            "dep_key":  label,
                            "dep_id":   label_to_dep[label],
                            "dep_name": None,
                        })
    return rows


def _process_paper_llm(statements: list, client, model: str) -> list:
    if len(statements) < 2:
        return []

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
            val = _truncate(s.get(field))
            if val:
                item[field] = val
        stmt_items.append(item)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _render("intrapaper_llm_system.j2")},
                {"role": "user",   "content": json.dumps(stmt_items, ensure_ascii=False)},
            ],
            temperature=0,
            max_tokens=4096,
        )
        text = response.choices[0].message.content.strip()
        # Strip markdown code fences if the model wraps its output
        if text.startswith("```"):
            text = re.sub(r"^```[^\n]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text.strip())
        data = json.loads(text)
        deps = data.get("dependencies", [])
    except Exception as e:
        tqdm.write(f"[intrapaper llm] error: {e}")
        return []

    rows = []
    seen = set()
    for dep in deps:
        src_label = dep.get("src", "").strip()
        dep_label = dep.get("dep", "").strip()
        location  = dep.get("location", "").strip()

        if location not in ("body", "note", "proof", "pre_context", "post_context"):
            continue
        src_stmt_id = id_to_statement_id.get(src_label)
        dep_stmt_id = id_to_statement_id.get(dep_label)
        if not src_stmt_id or not dep_stmt_id or src_stmt_id == dep_stmt_id:
            continue

        key = (src_stmt_id, dep_stmt_id, location)
        if key in seen:
            continue
        seen.add(key)

        rows.append({
            "src_id":   src_stmt_id,
            "location": location,
            "cite_key": None,
            "cite_id":  None,
            "dep_key":  dep.get("phrase") or None,
            "dep_id":   dep_stmt_id,
            "dep_name": None,
        })
    return rows


def _merge(det_rows: list, llm_rows: list) -> list:
    """Merge deterministic and LLM rows, assigning method to each.

    Two rows are considered the same dependency if they share (src_id, dep_id),
    regardless of location — the same statement pair may be referenced in different
    fields by each method. For deterministic+llm rows, the deterministic row (with
    its \\label dep_key) is kept; the LLM phrase is not needed.
    """
    llm_keys = {(r["src_id"], r["dep_id"]) for r in llm_rows}

    merged = []
    det_keys = set()
    for r in det_rows:
        key = (r["src_id"], r["dep_id"])
        det_keys.add(key)
        method = "deterministic+llm" if key in llm_keys else "deterministic"
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
    do_llm: bool,
    model: Optional[str] = None,
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
                "condition": """
                    NOT EXISTS (
                        SELECT 1 FROM statement
                        JOIN informal_dependency ON informal_dependency.src_id = statement.statement_id
                        WHERE statement.paper_id = paper.paper_id
                          AND informal_dependency.cite_key IS NULL
                    )
                """
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
            for paper in papers:
                stmts = statements_by_paper[paper["paper_id"]]
                det_rows = _process_paper_deterministic(stmts) if do_deterministic else []
                llm_rows = _process_paper_llm(stmts, llm_client, model) if do_llm else []
                batch_rows.extend(_merge(det_rows, llm_rows))

            if batch_rows:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM informal_dependency
                        WHERE cite_key IS NULL
                          AND src_id = ANY(%s::uuid[])
                        """,
                        (list({row["src_id"] for row in batch_rows}),)
                    )
                upsert_rows(conn, table="informal_dependency", rows=batch_rows)
                conn.commit()

            pbar.update(len(papers))
