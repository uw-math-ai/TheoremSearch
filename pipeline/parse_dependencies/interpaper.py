import re
import traceback
from collections import defaultdict
from typing import List, Dict, Optional
from tqdm import tqdm
from psycopg2.extensions import connection

from rds.utils.query import build_query, get_query_count
from rds.utils.paginate import paginate_query
from rds.utils.upsert import upsert_rows

_CITE_PATTERN = re.compile(
    r'\\cite\w*'
    r'(?:\[[^\]]*\])?'
    r'(\[[^\]]*\])?'
    r'\{([^}]+)\}',
    re.IGNORECASE
)
_THEOREM_REF_PATTERN = re.compile(
    r'(?:^|(?:see|cf\.?|by|using)\s+)(Theorem|Lemma|Proposition|Corollary)\s+([\w.]+)\s*$',
    re.IGNORECASE
)
_CONTEXT_BEFORE_PATTERN = re.compile(
    r'(?:by|using)\s+(Theorem|Lemma|Proposition|Corollary)\s+([\w.]+)\s*$'
    r'|(?<!\w)(Theorem|Lemma|Proposition|Corollary)\s+([\w.]+)\s+in\s*$',
    re.IGNORECASE
)


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


def get_interpaper_dependencies(
    conn: connection,
    arxiv_id: str,
    similarity_threshold: float,
) -> List[Dict]:
    """
    Resolve inter-paper statement dependencies for a single arXiv paper.

    Strategy (cite-first):
      1. Read bibliography JSONB from arxiv_paper_metadata.
      2. Fetch this paper's statements and parse \\cite keys per location
         (body / note / proof). All cites are kept — bare cites record the
         paper-level dependency; specific cites additionally resolve dep_id.
      3. Resolve bib entries only for cited keys.
         Stage 1: exact arXiv ID match.
         Stage 2: pg_trgm title match, restricted to arxiv IDs in the bib.
      4. Batch-resolve dep statement UUIDs for cites that name a specific theorem.
      5. Emit one row per (src, cite, location) triple. dep_id is None for bare
         cites or when the specific statement could not be resolved.
    """
    # ------------------------------------------------------------------ #
    # Step 1 – read bibliography from DB                                  #
    # ------------------------------------------------------------------ #
    with conn.cursor() as cur:
        cur.execute(
            "SELECT bibliography FROM arxiv_paper_metadata WHERE arxiv_id = %s",
            (arxiv_id,),
        )
        row = cur.fetchone()
    if not row or row[0] is None:
        return []
    bib: Dict[str, Dict] = row[0]
    if not bib:
        return []

    # ------------------------------------------------------------------ #
    # Step 2 – fetch statements and parse cite keys per location          #
    # ------------------------------------------------------------------ #
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.statement_id, s.body, s.proof, im.note
            FROM statement s
            INNER JOIN informal_metadata im ON im.statement_id = s.statement_id
            INNER JOIN paper p ON p.paper_id = s.paper_id
            WHERE p.kind = 'paper' AND p.external_id = %s
            """,
            (arxiv_id,),
        )
        statements = [
            dict(zip(["statement_id", "body", "proof", "note"], row))
            for row in cur.fetchall()
        ]

    if not statements:
        return []

    # statement_id → list of (bib_key, theorem_type, theorem_ref, location)
    statement_cites: Dict[str, list] = defaultdict(list)
    needed_keys: set = set()

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
                quad = (cite["key"], cite["type"], cite["ref"], location)
                if quad not in seen:
                    seen.add(quad)
                    statement_cites[stmt["statement_id"]].append(quad)
                    needed_keys.add(cite["key"])

    if not needed_keys:
        return []

    # ------------------------------------------------------------------ #
    # Step 3 – resolve only the needed bib keys                           #
    # ------------------------------------------------------------------ #
    needed_bib = {k: v for k, v in bib.items() if k in needed_keys}
    if not needed_bib:
        return []

    resolved: Dict[str, str] = {}  # bib_key → paper_id (UUID)

    # Stage 1: exact arXiv ID match
    arxiv_to_key = {
        meta["arxiv_id"]: key
        for key, meta in needed_bib.items()
        if meta.get("arxiv_id")
    }
    if arxiv_to_key:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT paper_id, external_id FROM paper
                WHERE kind = 'paper' AND external_id = ANY(%s)
                """,
                (list(arxiv_to_key),),
            )
            for paper_id, external_id in cur.fetchall():
                bib_key = arxiv_to_key[external_id]
                if bib_key not in resolved:
                    resolved[bib_key] = paper_id

    # Stage 2: pg_trgm title match for remainder
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
            for bib_key, paper_id in cur.fetchall():
                if bib_key not in resolved:
                    resolved[bib_key] = paper_id

    # ------------------------------------------------------------------ #
    # Step 4 – batch-resolve dep statement UUIDs                          #
    # ------------------------------------------------------------------ #
    lookups = list(dict.fromkeys(
        (resolved[key], ttype, tref)
        for cites in statement_cites.values()
        for key, ttype, tref, _ in cites
        if key in resolved and ttype and tref
    ))

    dep_id_cache: Dict[tuple, Optional[str]] = {}
    if lookups:
        paper_ids_l = [lk[0] for lk in lookups]
        types_l     = [lk[1] for lk in lookups]
        refs_l      = [lk[2] for lk in lookups]

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
                (paper_ids_l, types_l, refs_l),
            )
            for pid, typ, ref, sid in cur.fetchall():
                dep_id_cache.setdefault((pid, typ, ref), sid)

    for lk in lookups:
        dep_id_cache.setdefault(lk, None)

    # ------------------------------------------------------------------ #
    # Step 5 – build dependency rows                                      #
    # ------------------------------------------------------------------ #
    dependency_rows: List[Dict] = []

    for stmt in statements:
        for bib_key, theorem_type, theorem_ref, location in statement_cites.get(stmt["statement_id"], []):
            cite_id = resolved.get(bib_key)  # None if unresolved — still emit the row
            dep_id  = dep_id_cache.get((cite_id, theorem_type, theorem_ref)) if cite_id else None

            dependency_rows.append({
                "src_id":   stmt["statement_id"],
                "location": location,
                "cite_id":  cite_id,
                "cite_key": bib_key,
                "dep_id":   dep_id,
                "dep_key":  theorem_ref,
                "dep_name": f"{theorem_type.capitalize()} {theorem_ref}" if theorem_type else None,
            })

    return dependency_rows


def connect_interpaper_dependencies(
    conn: connection,
    condition: str,
    condition_params: List[str],
    overwrite: bool,
    batch_size: int,
    similarity_threshold: float,
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
                "condition": """
                    EXISTS (
                        SELECT 1 FROM statement s
                        WHERE s.paper_id = p.paper_id
                    )
                """
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
                try:
                    rows = get_interpaper_dependencies(
                        conn=conn,
                        arxiv_id=paper["external_id"],
                        similarity_threshold=similarity_threshold,
                    )
                    batch_rows.extend(rows)
                except Exception:
                    tqdm.write(f"[interpaper] skipping {paper['external_id']}:\n{traceback.format_exc()}")

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
