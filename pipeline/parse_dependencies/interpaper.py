import re
import json
import os
import traceback
from collections import defaultdict
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from tqdm import tqdm
from jinja2 import Environment, FileSystemLoader
from psycopg2.extensions import connection

from rds.utils.query import build_query, get_query_count
from rds.utils.paginate import paginate_query
from rds.utils.upsert import upsert_rows
from ..constants import STATEMENT_KINDS

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_jinja_env = Environment(loader=FileSystemLoader(_PROMPTS_DIR), keep_trailing_newline=True)

def _render(template_name: str, **kwargs) -> str:
    return _jinja_env.get_template(template_name).render(**kwargs)

_KINDS_RE = "|".join(re.escape(k) for k in sorted(STATEMENT_KINDS, key=len, reverse=True))

_CITE_PATTERN = re.compile(
    r'\\cite\w*'
    r'(?:\[[^\]]*\])?'
    r'(\[[^\]]*\])?'
    r'\{([^}]+)\}',
    re.IGNORECASE
)
_THEOREM_REF_PATTERN = re.compile(
    rf'(?:^|(?:see|cf\.?|by|using)\s+)({_KINDS_RE})\s+([\w.]+)\s*$',
    re.IGNORECASE
)
_CONTEXT_BEFORE_PATTERN = re.compile(
    rf'(?:by|using)\s+({_KINDS_RE})\s+([\w.]+)\s*$'
    rf'|(?<!\w)({_KINDS_RE})\s+([\w.]+)\s+in\s*$',
    re.IGNORECASE
)
_DEP_NAME_PATTERN = re.compile(
    rf'^({_KINDS_RE})\s+([\w.]+)$',
    re.IGNORECASE
)

_FIELD_MAX_CHARS = 1000


def _truncate(text: Optional[str]) -> Optional[str]:
    if text and len(text) > _FIELD_MAX_CHARS:
        return text[:_FIELD_MAX_CHARS] + "…"
    return text


def _parse_dep_name(dep_name: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Parse 'Theorem 3.2' → ('theorem', '3.2'). Returns (None, None) if unrecognized."""
    if not dep_name:
        return None, None
    m = _DEP_NAME_PATTERN.match(dep_name.strip())
    if m:
        return m.group(1).lower(), m.group(2)
    return None, None


def _parse_cites(field: str) -> List[Dict]:
    results = []
    for m in _CITE_PATTERN.finditer(field):
        raw = m.group(0)
        bracket_args = re.findall(r'\[([^\]]*)\]', raw[raw.find('\\'):raw.rfind('{')])
        opt_arg = bracket_args[0] if bracket_args else None

        theorem_type = theorem_ref = None
        if opt_arg:
            rm = _THEOREM_REF_PATTERN.match(opt_arg.strip())
            if rm:
                theorem_type = rm.group(1).lower()
                theorem_ref  = rm.group(2)
        if theorem_type is None:
            context = field[max(0, m.start() - 50): m.start()]
            cm = _CONTEXT_BEFORE_PATTERN.search(context)
            if cm:
                theorem_type = (cm.group(1) or cm.group(3)).lower()
                theorem_ref  = cm.group(2) or cm.group(4)

        for key in m.group(2).split(","):
            results.append({"key": key.strip(), "type": theorem_type, "ref": theorem_ref})

    return results


# ------------------------------------------------------------------ #
# Shared resolution helpers                                           #
# ------------------------------------------------------------------ #

def _resolve_bib_keys(
    conn: connection,
    needed_bib: Dict[str, Dict],
    similarity_threshold: float,
    bibtex: bool = True,
) -> Dict[str, str]:
    """Resolve bib_key → paper_id (UUID) via arXiv ID match then title match.

    When bibtex=False the 'title' field is raw bibitem text that contains the
    real title somewhere inside it, so we check whether the candidate paper's
    clean title is a substring of the query string instead of using trigram
    similarity.
    """
    resolved: Dict[str, str] = {}

    arxiv_to_key = {
        meta["arxiv_id"]: key
        for key, meta in needed_bib.items()
        if meta.get("arxiv_id")
    }
    if arxiv_to_key:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT paper_id, external_id FROM paper WHERE kind = 'paper' AND external_id = ANY(%s)",
                (list(arxiv_to_key),),
            )
            for paper_id, external_id in cur.fetchall():
                bib_key = arxiv_to_key[external_id]
                if bib_key not in resolved:
                    resolved[bib_key] = paper_id

    unresolved_with_title = {
        key: meta
        for key, meta in needed_bib.items()
        if key not in resolved and meta.get("title")
    }
    if unresolved_with_title:
        keys_arr      = list(unresolved_with_title)
        titles_arr    = [unresolved_with_title[k]["title"] for k in keys_arr]
        all_arxiv_ids = [meta["arxiv_id"] for meta in needed_bib.values() if meta.get("arxiv_id")]

        with conn.cursor() as cur:
            if bibtex:
                cur.execute(
                    """
                    SELECT bib_key, p.paper_id
                    FROM unnest(%s::text[], %s::text[]) AS q(bib_key, query_title)
                    JOIN LATERAL (
                        SELECT paper_id FROM paper
                        WHERE kind = 'paper'
                          AND external_id = ANY(%s)
                          AND title IS NOT NULL
                          AND similarity(LOWER(title), LOWER(q.query_title)) >= %s
                        ORDER BY similarity(LOWER(title), LOWER(q.query_title)) DESC
                        LIMIT 1
                    ) p ON TRUE
                    """,
                    (keys_arr, titles_arr, all_arxiv_ids, similarity_threshold),
                )
            else:
                # title field is raw bibitem text; check if the paper's clean
                # title appears as a substring inside it
                cur.execute(
                    """
                    SELECT bib_key, p.paper_id
                    FROM unnest(%s::text[], %s::text[]) AS q(bib_key, query_title)
                    JOIN LATERAL (
                        SELECT paper_id FROM paper
                        WHERE kind = 'paper'
                          AND external_id = ANY(%s)
                          AND title IS NOT NULL
                          AND LOWER(q.query_title) LIKE '%%' || LOWER(title) || '%%'
                        LIMIT 1
                    ) p ON TRUE
                    """,
                    (keys_arr, titles_arr, all_arxiv_ids),
                )
            for bib_key, paper_id in cur.fetchall():
                if bib_key not in resolved:
                    resolved[bib_key] = paper_id

    return resolved


def _resolve_dep_ids(
    conn: connection,
    lookups: List[Tuple[str, str, str]],  # (paper_id, theorem_type, theorem_ref)
) -> Dict[Tuple, Optional[str]]:
    """Batch-resolve (paper_id, type, ref) → statement_id."""
    dep_id_cache: Dict[tuple, Optional[str]] = {}
    if not lookups:
        return dep_id_cache

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT q.paper_id, q.type, q.ref, s.statement_id
            FROM unnest(%s::uuid[], %s::text[], %s::text[])
                AS q(paper_id, type, ref)
            LEFT JOIN LATERAL (
                SELECT s.statement_id
                FROM statement s
                INNER JOIN informal_metadata im ON im.statement_id = s.statement_id
                WHERE s.paper_id    = q.paper_id
                  AND LOWER(s.kind) = LOWER(q.type)
                  AND im.ref        = q.ref
                LIMIT 1
            ) s ON TRUE
            """,
            ([lk[0] for lk in lookups], [lk[1] for lk in lookups], [lk[2] for lk in lookups]),
        )
        for pid, typ, ref, sid in cur.fetchall():
            dep_id_cache.setdefault((pid, typ, ref), sid)

    for lk in lookups:
        dep_id_cache.setdefault(lk, None)

    return dep_id_cache


def _build_rows(
    conn: connection,
    bib: Dict[str, Dict],
    # stmt_id → list of (cite_key, theorem_type, theorem_ref, location, dep_key_or_phrase)
    statement_cites: Dict[str, List[Tuple]],
    similarity_threshold: float,
    bibtex: bool = True,
) -> List[Dict]:
    """Resolve bib keys and dep IDs, then build dependency rows."""
    needed_keys = {t[0] for cites in statement_cites.values() for t in cites}
    needed_bib  = {k: v for k, v in bib.items() if k in needed_keys}
    if not needed_bib:
        return []

    resolved = _resolve_bib_keys(conn, needed_bib, similarity_threshold, bibtex=bibtex)

    lookups = list(dict.fromkeys(
        (resolved[key], ttype, tref)
        for cites in statement_cites.values()
        for key, ttype, tref, *_ in cites
        if key in resolved and ttype and tref
    ))
    dep_id_cache = _resolve_dep_ids(conn, lookups)

    rows: List[Dict] = []
    for stmt_id, cites in statement_cites.items():
        for cite_key, theorem_type, theorem_ref, location, dep_key in cites:
            cite_id = resolved.get(cite_key)
            dep_id  = dep_id_cache.get((cite_id, theorem_type, theorem_ref)) if cite_id else None
            rows.append({
                "src_id":   stmt_id,
                "location": location,
                "cite_id":  cite_id,
                "cite_key": cite_key,
                "dep_id":   dep_id,
                "dep_key":  dep_key,
                "dep_name": f"{theorem_type.capitalize()} {theorem_ref}" if theorem_type else None,
            })
    return rows


# ------------------------------------------------------------------ #
# Deterministic path                                                  #
# ------------------------------------------------------------------ #

def _get_deterministic_deps(
    conn: connection,
    arxiv_id: str,
    bib: Dict[str, Dict],
    statements: List[Dict],
    similarity_threshold: float,
    bibtex: bool = True,
) -> List[Dict]:
    statement_cites: Dict[str, list] = defaultdict(list)

    for stmt in statements:
        seen: set = set()
        for location, field in [
            ("body",  stmt["body"]),
            ("note",  stmt.get("note")),
            ("proof", stmt.get("proof")),
        ]:
            if not field or r'\cite' not in field:
                continue
            for cite in _parse_cites(field):
                quad = (cite["key"], cite["type"], cite["ref"], location, None)
                if quad[:4] not in seen:
                    seen.add(quad[:4])
                    statement_cites[stmt["statement_id"]].append(quad)

    return _build_rows(conn, bib, statement_cites, similarity_threshold, bibtex=bibtex)


# ------------------------------------------------------------------ #
# LLM path                                                            #
# ------------------------------------------------------------------ #

def _get_llm_deps(
    conn: connection,
    arxiv_id: str,
    bib: Dict[str, Dict],
    statements: List[Dict],
    similarity_threshold: float,
    client,
    model: str,
    bibtex: bool = True,
) -> Tuple[List[Dict], int, int]:
    """Returns (rows, input_tokens, output_tokens)."""
    if not statements or not bib:
        return [], 0, 0

    # Pre-filter bib to keys that appear somewhere in the statement text,
    # so we don't send hundreds of irrelevant entries to the LLM.
    all_text = " ".join(
        (s.get(f) or "")
        for s in statements
        for f in ("body", "proof", "note", "pre_context", "post_context")
    )
    bib_for_llm = {
        k: {f: v[f] for f in ("title", "arxiv_id") if v.get(f)}
        for k, v in bib.items()
        if k in all_text
    }
    if not bib_for_llm:
        return [], 0, 0

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
            val = _truncate(s.get(field))
            if val:
                item[field] = val
        stmt_items.append(item)

    user_content = json.dumps(
        {"bibliography": bib_for_llm, "statements": stmt_items},
        ensure_ascii=False,
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _render("interpaper_llm_system.j2")},
                {"role": "user",   "content": user_content},
            ],
            temperature=0,
            max_tokens=8192,
        )
        usage = response.usage
        in_tokens  = getattr(usage, "prompt_tokens",     0) or 0
        out_tokens = getattr(usage, "completion_tokens", 0) or 0
        text = response.choices[0].message.content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[^\n]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text.strip())
        data = json.loads(text)
        citations = data.get("citations", [])
    except Exception as e:
        tqdm.write(f"[interpaper llm] {arxiv_id}: {e}")
        return [], 0, 0

    statement_cites: Dict[str, list] = defaultdict(list)
    seen: set = set()

    for c in citations:
        src_label = c.get("src", "").strip()
        cite_key  = c.get("cite_key", "").strip()
        dep_name  = c.get("dep_name") or None
        location  = c.get("location", "").strip()
        phrase    = c.get("phrase") or None

        if location not in ("body", "note", "proof", "pre_context", "post_context"):
            continue
        if cite_key not in bib:
            continue  # LLM hallucinated a key not in the bibliography

        stmt_id = id_to_statement_id.get(src_label)
        if not stmt_id:
            continue

        theorem_type, theorem_ref = _parse_dep_name(dep_name)
        key = (stmt_id, cite_key, theorem_ref, location)
        if key in seen:
            continue
        seen.add(key)

        statement_cites[stmt_id].append((cite_key, theorem_type, theorem_ref, location, phrase))

    return _build_rows(conn, bib, statement_cites, similarity_threshold, bibtex=bibtex), in_tokens, out_tokens


# ------------------------------------------------------------------ #
# Merge                                                               #
# ------------------------------------------------------------------ #

def _merge(det_rows: list, llm_rows: list) -> list:
    """Merge deterministic and LLM rows, assigning method to each.

    Two rows are the same citation if they share (src_id, cite_key).
    For deterministic+llm rows, the deterministic row is kept as-is.
    """
    llm_keys = {(r["src_id"], r["cite_key"]) for r in llm_rows}

    merged = []
    det_keys = set()
    for r in det_rows:
        key = (r["src_id"], r["cite_key"])
        det_keys.add(key)
        method = "deterministic+llm" if key in llm_keys else "deterministic"
        merged.append({**r, "method": method})

    for r in llm_rows:
        key = (r["src_id"], r["cite_key"])
        if key not in det_keys:
            merged.append({**r, "method": "llm"})

    return merged


# ------------------------------------------------------------------ #
# Main entry point                                                    #
# ------------------------------------------------------------------ #

def connect_interpaper_dependencies(
    conn: connection,
    condition: str,
    condition_params: List[str],
    overwrite: bool,
    batch_size: int,
    similarity_threshold: float,
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
            "SELECT p.paper_id, p.external_id"
            " FROM paper p"
            " INNER JOIN arxiv_paper_metadata AS apm ON apm.arxiv_id = p.external_id"
            + (" LEFT JOIN arxiv_parse_status AS aps ON aps.arxiv_id = p.external_id" if condition and "aps." in condition else "")
        ),
        where_clauses=[
            {
                "if": condition,
                "condition": condition,
                "params": condition_params,
            },
            {
                "if": not overwrite,
                "condition": """
                    NOT EXISTS (
                        SELECT 1 FROM informal_dependency d
                        INNER JOIN statement s ON s.statement_id = d.src_id
                        WHERE s.paper_id = p.paper_id
                          AND d.cite_key IS NOT NULL
                    )
                """
            },
            {
                "if": True,
                "condition": "EXISTS (SELECT 1 FROM statement s WHERE s.paper_id = p.paper_id)"
            },
            {
                "if": True,
                "condition": "p.kind = 'paper'"
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

    with tqdm(total=count, dynamic_ncols=True, unit=" papers", desc="Interpaper") as pbar:
        for papers in paginate_query(
            conn,
            base_query=query,
            base_params=params,
            order_by="paper_id",
            page_size=batch_size,
        ):
            batch_rows: List = []

            for paper in papers:
                arxiv_id = paper["external_id"]
                try:
                    # Fetch shared data once per paper
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT bibliography, bibtex FROM arxiv_paper_metadata WHERE arxiv_id = %s",
                            (arxiv_id,),
                        )
                        row = cur.fetchone()
                    bib: Dict[str, Dict] = (row[0] or {}) if row else {}
                    bibtex: bool = bool(row[1]) if row else True

                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            SELECT s.statement_id, s.kind, s.body, s.proof,
                                   im.ref, im.note, im.pre_context, im.post_context
                            FROM statement s
                            INNER JOIN informal_metadata im ON im.statement_id = s.statement_id
                            INNER JOIN paper p ON p.paper_id = s.paper_id
                            WHERE p.kind = 'paper' AND p.external_id = %s
                            """,
                            (arxiv_id,),
                        )
                        statements = [
                            dict(zip([
                                "statement_id", "kind", "body", "proof",
                                "ref", "note", "pre_context", "post_context"
                            ], r))
                            for r in cur.fetchall()
                        ]

                    if not statements or not bib:
                        continue

                    det_rows = _get_deterministic_deps(
                        conn, arxiv_id, bib, statements, similarity_threshold, bibtex=bibtex,
                    ) if do_deterministic else []

                    if do_llm:
                        llm_rows, in_tok, out_tok = _get_llm_deps(
                            conn, arxiv_id, bib, statements, similarity_threshold,
                            llm_client, model, bibtex=bibtex,
                        )
                        total_in_tokens  += in_tok
                        total_out_tokens += out_tok
                        pbar.set_postfix({
                                "in":  _fmt_tokens(total_in_tokens),
                                "out": _fmt_tokens(total_out_tokens),
                            })
                    else:
                        llm_rows = []

                    batch_rows.extend(_merge(det_rows, llm_rows))

                except Exception:
                    tqdm.write(f"[interpaper] skipping {arxiv_id}:\n{traceback.format_exc()}")

            if batch_rows:
                source_ids = list({row["src_id"] for row in batch_rows})
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM informal_dependency
                        WHERE cite_key IS NOT NULL
                          AND src_id = ANY(%s::uuid[])
                        """,
                        (source_ids,)
                    )
                upsert_rows(conn, table="informal_dependency", rows=batch_rows)
                conn.commit()

            pbar.update(len(papers))
