import re
import os
import sys
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Iterable, List, Dict, Optional, Tuple
from tqdm import tqdm
import yaml
from jinja2 import Environment, FileSystemLoader
from psycopg2.extensions import connection

from rds.utils.query import build_query, get_query_count
from rds.utils.paginate import paginate_query
from rds.utils.upsert import upsert_rows
from ..constants import STATEMENT_KINDS
from .llm_utils import build_stmt_id_map, parse_inter_llm_text, proximity_score, proximity_keywords
from .intrapaper import _overwrite_method_clause, _reset_methods, _PROOF_START_RE

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

def _truncate(text: Optional[str], max_chars: int, tail: bool = False) -> Optional[str]:
    if text and len(text) > max_chars:
        return ("…" + text[-max_chars:]) if tail else (text[:max_chars] + "…")
    return text


def _parse_dep_name(dep_name: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Parse 'Theorem 3.2' → ('theorem', '3.2'). Returns (None, None) if unrecognized."""
    if not dep_name:
        return None, None
    m = _DEP_NAME_PATTERN.match(dep_name.strip())
    if m:
        return m.group(1).lower(), m.group(2)
    return None, None


def _iter_cites(field: str):
    """Yield (match_start, verbatim, cite_dict) for each \\cite occurrence in field."""
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
            yield m.start(), m.group(0), {"key": key.strip(), "type": theorem_type, "ref": theorem_ref}


def _parse_cites(field: str) -> List[Dict]:
    return [cite for _, _, cite in _iter_cites(field)]


# ------------------------------------------------------------------ #
# Shared resolution helpers                                           #
# ------------------------------------------------------------------ #

def _resolve_bib_keys(
    conn: connection,
    needed_bib: Dict[str, Dict],
    similarity_threshold: float,
    bibtex: bool = True,
    reference_ids: Optional[List[str]] = None,
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
        keys_arr   = list(unresolved_with_title)
        titles_arr = [unresolved_with_title[k]["title"] for k in keys_arr]
        # Use Semantic Scholar reference_ids as the candidate pool when available;
        # they cover all references regardless of whether the bib entry has an arXiv ID.
        # Strip the "ARXIV:" prefix to match paper.external_id format.
        if reference_ids:
            all_arxiv_ids = [
                rid[len("ARXIV:"):] for rid in reference_ids
                if rid.upper().startswith("ARXIV:")
            ]
        else:
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
    reference_ids: Optional[List[str]] = None,
) -> List[Dict]:
    """Resolve bib keys and dep IDs, then build dependency rows."""
    needed_keys = {t[0] for cites in statement_cites.values() for t in cites}
    needed_bib  = {k: v for k, v in bib.items() if k in needed_keys}
    if not needed_bib:
        return []

    resolved = _resolve_bib_keys(conn, needed_bib, similarity_threshold, bibtex=bibtex, reference_ids=reference_ids)

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
    run_pure: bool = True,
    run_heuristic: bool = True,
    proximity_threshold: float = 0.5,
    reference_ids: Optional[List[str]] = None,
) -> List[Dict]:
    regular_cites:   Dict[str, list] = defaultdict(list)
    heuristic_cites: Dict[str, list] = defaultdict(list)

    for stmt in statements:
        seen: set = set()

        # ── body / note / proof: all \cite hits → regular ─────────────────
        if run_pure:
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
                        regular_cites[stmt["statement_id"]].append(quad)

        # ── pre_context / post_context: proximity-filtered → heuristic ────
        # post_context that opens with a proof marker is treated as a proof:
        # all \cite hits are captured without a proximity requirement.
        if run_heuristic:
            for location, field in [
                ("pre_context",  stmt.get("pre_context")),
                ("post_context", stmt.get("post_context")),
            ]:
                if not field or r'\cite' not in field:
                    continue
                is_proof_context = (location == "post_context" and bool(_PROOF_START_RE.match(field)))
                for cmd_start, verbatim, cite in _iter_cites(field):
                    if not is_proof_context and proximity_score(field, cmd_start) < proximity_threshold:
                        continue
                    kw = "proof" if is_proof_context else proximity_keywords(field, cmd_start, proximity_threshold)
                    dep_key = f"{cite['key']}|{kw}" if kw else f"{cite['key']}|"
                    quad = (cite["key"], cite["type"], cite["ref"], location, dep_key)
                    if quad[:4] not in seen:
                        seen.add(quad[:4])
                        heuristic_cites[stmt["statement_id"]].append(quad)

    regular_rows   = [{**r, "method": "deterministic"} for r in _build_rows(conn, bib, regular_cites,   similarity_threshold, bibtex=bibtex, reference_ids=reference_ids)] if run_pure      else []
    heuristic_rows = [{**r, "method": "heuristic"}     for r in _build_rows(conn, bib, heuristic_cites, similarity_threshold, bibtex=bibtex, reference_ids=reference_ids)] if run_heuristic  else []
    return regular_rows + heuristic_rows


# ------------------------------------------------------------------ #
# Merge                                                               #
# ------------------------------------------------------------------ #

def _merge(det_rows: list, llm_rows: list) -> list:
    """Merge deterministic/heuristic and LLM rows, assigning final method to each.

    Two rows are the same citation if they share (src_id, cite_key).
    Base method ("deterministic" or "heuristic") is preserved from det_rows;
    "+llm" is appended when the LLM independently found the same citation.
    """
    llm_keys = {(r["src_id"], r["cite_key"]) for r in llm_rows}

    merged = []
    det_keys = set()
    for r in det_rows:
        key = (r["src_id"], r["cite_key"])
        det_keys.add(key)
        base = r.get("method", "deterministic")
        method = f"{base}+llm" if key in llm_keys else base
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
    do_heuristic: bool = True,
    proximity_threshold: float = 0.5,
    shard: int = 0,
    n_shards: int = 1,
):

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
                "condition": (
                    "NOT EXISTS ("
                    " SELECT 1 FROM informal_dependency d"
                    " INNER JOIN statement s ON s.statement_id = d.src_id"
                    " WHERE s.paper_id = p.paper_id"
                    " AND d.cite_key IS NOT NULL"
                    + _overwrite_method_clause(do_deterministic, do_heuristic, False, intra=False, alias="d")
                    + ")"
                ),
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
    total_deps = 0

    with tqdm(total=count, dynamic_ncols=True, unit=" papers", desc="Interpaper", file=sys.stdout) as pbar:
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
                            "SELECT bibliography, bibtex, reference_ids FROM arxiv_paper_metadata WHERE arxiv_id = %s",
                            (arxiv_id,),
                        )
                        row = cur.fetchone()
                    bib: Dict[str, Dict] = (row[0] or {}) if row else {}
                    bibtex: bool = bool(row[1]) if row else True
                    reference_ids: Optional[List[str]] = row[2] if row else None

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
                        conn, arxiv_id, bib, statements, similarity_threshold,
                        bibtex=bibtex, run_pure=do_deterministic, run_heuristic=do_heuristic,
                        proximity_threshold=proximity_threshold,
                        reference_ids=reference_ids,
                    ) if (do_deterministic or do_heuristic) else []

                    batch_rows.extend(det_rows)

                except Exception:
                    tqdm.write(f"[interpaper] skipping {arxiv_id}:\n{traceback.format_exc()}")

            total_deps += len(batch_rows)
            pbar.set_postfix({"deps": total_deps})

            if batch_rows:
                source_ids = list({row["src_id"] for row in batch_rows})
                with conn.cursor() as cur:
                    _reset_methods(cur, source_ids, do_deterministic, do_heuristic, False, intra=False)
                upsert_rows(conn, table="informal_dependency", rows=batch_rows)
                with conn.cursor() as cur:
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
                    # Dedup inter: keep one row per (src_id, cite_key)
                    cur.execute("""
                        DELETE FROM informal_dependency
                        WHERE cite_key IS NOT NULL
                          AND src_id = ANY(%s::uuid[])
                          AND ctid NOT IN (
                              SELECT DISTINCT ON (src_id, cite_key) ctid
                              FROM informal_dependency
                              WHERE cite_key IS NOT NULL AND src_id = ANY(%s::uuid[])
                              ORDER BY src_id, cite_key,
                                  CASE method
                                      WHEN 'deterministic+llm' THEN 1
                                      WHEN 'deterministic'     THEN 2
                                      WHEN 'heuristic+llm'     THEN 3
                                      WHEN 'heuristic'         THEN 4
                                      ELSE 5
                                  END,
                                  CASE WHEN dep_name IS NOT NULL THEN 1 ELSE 2 END,
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

def connect_inter_llm_results(
    conn: connection,
    results: Iterable[Tuple[str, str]],
    similarity_threshold: float,
    batch_size: int = 256,
) -> Dict[str, int]:
    """Write pre-computed LLM inter-paper results (arxiv_id, text) into the DB.

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
                "DELETE FROM informal_dependency WHERE cite_key IS NOT NULL AND method = 'llm' AND src_id = ANY(%s::uuid[])",
                (src_ids,),
            )
            cur.execute(
                "UPDATE informal_dependency SET method = 'deterministic' WHERE cite_key IS NOT NULL AND method = 'deterministic+llm' AND src_id = ANY(%s::uuid[])",
                (src_ids,),
            )
            cur.execute(
                "UPDATE informal_dependency SET method = 'heuristic' WHERE cite_key IS NOT NULL AND method = 'heuristic+llm' AND src_id = ANY(%s::uuid[])",
                (src_ids,),
            )
        if pending_rows:
            upsert_rows(conn, "informal_dependency", pending_rows)
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE informal_dependency d SET method = 'deterministic+llm'
                WHERE d.cite_key IS NOT NULL AND d.method = 'deterministic'
                  AND d.src_id = ANY(%s::uuid[])
                  AND EXISTS (
                      SELECT 1 FROM informal_dependency
                      WHERE src_id = d.src_id AND cite_key = d.cite_key AND method = 'llm'
                  )
            """, (src_ids,))
            cur.execute("""
                UPDATE informal_dependency d SET method = 'heuristic+llm'
                WHERE d.cite_key IS NOT NULL AND d.method = 'heuristic'
                  AND d.src_id = ANY(%s::uuid[])
                  AND EXISTS (
                      SELECT 1 FROM informal_dependency
                      WHERE src_id = d.src_id AND cite_key = d.cite_key AND method = 'llm'
                  )
            """, (src_ids,))
            cur.execute("""
                DELETE FROM informal_dependency
                WHERE cite_key IS NOT NULL
                  AND src_id = ANY(%s::uuid[])
                  AND ctid NOT IN (
                      SELECT DISTINCT ON (src_id, cite_key) ctid
                      FROM informal_dependency
                      WHERE cite_key IS NOT NULL AND src_id = ANY(%s::uuid[])
                      ORDER BY src_id, cite_key,
                          CASE method
                              WHEN 'deterministic+llm' THEN 1
                              WHEN 'deterministic'     THEN 2
                              WHEN 'heuristic+llm'     THEN 3
                              WHEN 'heuristic'         THEN 4
                              ELSE 5
                          END,
                          CASE WHEN dep_name IS NOT NULL THEN 1 ELSE 2 END,
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

    for arxiv_id, text in tqdm(results, unit=" papers", desc="Connecting inter", dynamic_ncols=True):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT bibliography, bibtex, reference_ids FROM arxiv_paper_metadata WHERE arxiv_id = %s",
                (arxiv_id,),
            )
            row = cur.fetchone()
        if not row:
            tqdm.write(f"  Warning: no metadata for {arxiv_id}, skipping.")
            failed += 1
            continue
        bib, bibtex, reference_ids = row[0] or {}, bool(row[1]), row[2]

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
        statement_cites = parse_inter_llm_text(text, bib, id_to_stmt)
        if statement_cites is None:
            tqdm.write(f"  Warning: failed to parse LLM response for {arxiv_id}.")
            failed += 1
            continue

        rows = _build_rows(conn, bib, statement_cites, similarity_threshold, bibtex=bibtex, reference_ids=reference_ids)
        pending_rows.extend({**r, "method": "llm"} for r in rows)
        pending_stmt_ids.extend(s["statement_id"] for s in statements)
        written += len(rows)
        papers_buffered += 1

        if papers_buffered >= batch_size:
            _flush()

    _flush()
    return {"written": written, "failed": failed}
