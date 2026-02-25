import re
from collections import defaultdict
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from rds.utils.connect import get_rds_connection
from rds.utils.query import get_query_count
from rds.utils.paginate import paginate_query
from rds.utils.upsert import upsert_rows
from ..printing import print_script_header
from arXiTeX import parse_bibliography

# Matches \cite[Theorem 2.3]{key} or \cite[Lemma 1]{key,key2} etc.
_CITE_PATTERN = re.compile(
    r'\\cite\[([^\]]+)\]\{([^}]+)\}'   # with optional arg
    r'|\\cite\{([^}]+)\}'              # without optional arg
)

# Matches a theorem reference in the optional arg, e.g. "Theorem 2.3" or "Lemma A.1"
_THEOREM_REF_PATTERN = re.compile(
    r'^(Theorem|Lemma|Proposition|Corollary)\s+([\w.]+)$',
    re.IGNORECASE
)

def _parse_cites(body: str) -> list[dict]:
    """
    Returns list of {"key": ..., "type": ..., "ref": ...} dicts.
    type/ref are None when no structured optional arg is found.
    """
    results = []
    for m in _CITE_PATTERN.finditer(body):
        opt_arg, keys_with_opt, keys_bare = m.group(1), m.group(2), m.group(3)
        keys = (keys_with_opt or keys_bare).split(",")
        theorem_type, theorem_ref = None, None
        if opt_arg:
            rm = _THEOREM_REF_PATTERN.match(opt_arg.strip())
            if rm:
                theorem_type = rm.group(1).lower()  # stored lowercase in DB
                theorem_ref = rm.group(2)
        for key in keys:
            results.append({"key": key.strip(), "type": theorem_type, "ref": theorem_ref})
    return results

def _resolve_paper(conn, bib_metadata: dict, similarity_threshold: float) -> tuple[str, str] | None:
    """
    Try to resolve a bib entry to a (paper_id, source) pair.
    First tries exact arxiv_id match, then pg_trgm title similarity.
    Returns None if no match found above threshold.
    """
    # 1. Try exact arxiv_id match
    arxiv_id = bib_metadata.get("arxiv_id")
    if arxiv_id:
        with conn.cursor() as cur:
            cur.execute("SELECT id, source FROM paper WHERE id = %s LIMIT 1", (arxiv_id,))
            row = cur.fetchone()
            if row:
                return row[0], row[1]

    # 2. Try pg_trgm title similarity
    title = bib_metadata.get("title")
    if title:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, source, similarity(LOWER(title), LOWER(%s)) AS sim
                FROM paper
                WHERE title IS NOT NULL
                    AND similarity(LOWER(title), LOWER(%s)) >= %s
                ORDER BY sim DESC
                LIMIT 1
                """,
                (title, title, similarity_threshold)
            )
            row = cur.fetchone()
            if row:
                return row[0], row[1]

    return None

def _fetch_bibliographies(papers: list) -> dict[str, dict]:
    """
    Fetch bibliographies for a batch of papers in parallel.
    Returns a dict of paper_id -> bibliography.
    """
    results = {}

    def fetch(paper):
        paper_id = paper["id"]
        source = paper["source"]
        bib = parse_bibliography(arxiv_id=paper_id if source == "arXiv" else None) or {}
        return paper_id, bib

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(fetch, paper): paper for paper in papers}
        for future in as_completed(futures):
            paper_id, bib = future.result()
            results[paper_id] = bib

    return results

def _process_batch(conn, papers: list, batch_theorems: list, similarity_threshold: float) -> list:
    bibliographies = _fetch_bibliographies(papers)

    theorems_by_paper = defaultdict(list)
    for t in batch_theorems:
        theorems_by_paper[t["paper_id"]].append(t)

    dependency_rows = []

    for paper in papers:
        paper_id = paper["id"]
        paper_theorems = theorems_by_paper[paper_id]
        bibliography = bibliographies.get(paper_id, {})

        # Collect all unique cite keys across all theorems first
        all_cites: dict[tuple, dict] = {}  # (key, type, ref) -> cite
        for theorem in paper_theorems:
            for field in [theorem["body"], theorem.get("note"), theorem.get("proof")]:
                if not field:
                    continue
                for cite in _parse_cites(field):
                    k = (cite["key"], cite["type"], cite["ref"])
                    if k not in all_cites:
                        all_cites[k] = cite

        # Resolve each unique bib key once
        paper_match_cache: dict[str, tuple | None] = {}
        for cite in all_cites.values():
            if cite["key"] not in paper_match_cache:
                bib_metadata = bibliography.get(cite["key"], {})
                paper_match_cache[cite["key"]] = _resolve_paper(conn, bib_metadata, similarity_threshold)

        # Resolve each unique (key, type, ref) theorem once
        theorem_id_cache: dict[tuple, str | None] = {}
        for cite in all_cites.values():
            if cite["type"] and cite["ref"]:
                paper_match = paper_match_cache.get(cite["key"])
                if paper_match:
                    cache_key = (cite["key"], cite["type"], cite["ref"])
                    if cache_key not in theorem_id_cache:
                        dep_paper_id, dep_paper_source = paper_match
                        with conn.cursor() as cur:
                            cur.execute(
                                """
                                SELECT id FROM theorem
                                WHERE paper_id = %s AND source = %s AND type = %s AND ref = %s
                                LIMIT 1
                                """,
                                (dep_paper_id, dep_paper_source, cite["type"], cite["ref"])
                            )
                            row = cur.fetchone()
                            theorem_id_cache[cache_key] = row[0] if row else None

        # Now build rows using the caches
        for theorem in paper_theorems:
            cites_seen = set()
            for field in [theorem["body"], theorem.get("note"), theorem.get("proof")]:
                if not field:
                    continue
                for cite in _parse_cites(field):
                    k = (cite["key"], cite["type"], cite["ref"])
                    if k in cites_seen:
                        continue
                    cites_seen.add(k)

                    paper_match = paper_match_cache.get(cite["key"])
                    if paper_match is None:
                        continue

                    dep_paper_id, dep_paper_source = paper_match
                    theorem_name = f"{cite['type'].capitalize()} {cite['ref']}" if cite["type"] and cite["ref"] else ""
                    dep_theorem_id = theorem_id_cache.get((cite["key"], cite["type"], cite["ref"]))

                    if dep_theorem_id:
                        dependency_rows.append({
                            "src_theorem_id": theorem["id"],
                            "dep_key": cite["key"],
                            "dep_theorem_name": theorem_name,
                            "dep_paper_id": None,
                            "dep_paper_source": None,
                            "dep_theorem_id": dep_theorem_id,
                            "interpaper": True
                        })
                    else:
                        dependency_rows.append({
                            "src_theorem_id": theorem["id"],
                            "dep_key": cite["key"],
                            "dep_theorem_name": theorem_name,
                            "dep_paper_id": dep_paper_id,
                            "dep_paper_source": dep_paper_source,
                            "dep_theorem_id": None,
                            "interpaper": True
                        })

    return dependency_rows

def connect_interpaper_dependencies(batch_size: int, similarity_threshold: float = 0.8):
    """
    Connects inter-paper theorem dependencies by resolving \\cite references
    to papers (and optionally theorems within those papers) in the database.
    Requires pg_trgm extension for title matching.
    """
    print_script_header(
        action="Connecting interpaper theorem dependencies",
        params={
            "batch size": batch_size,
            "similarity threshold": similarity_threshold
        }
    )

    conn = get_rds_connection("v2")

    query = """
        SELECT id, source FROM paper
        WHERE id = '2109.06451'
    """

    count = get_query_count(conn, query)

    with tqdm(total=count, dynamic_ncols=True, unit=" papers") as pbar:
        for papers in paginate_query(
            conn,
            base_query=query,
            order_by="id",
            page_size=batch_size
        ):
            paper_ids = [p["id"] for p in papers]
            sources = [p["source"] for p in papers]

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, paper_id, body, note, proof FROM theorem WHERE paper_id = ANY(%s) AND source = ANY(%s)",
                    (paper_ids, sources)
                )
                batch_theorems = [
                    {
                        key: val
                        for key, val in zip(["id", "paper_id", "body", "note", "proof"], row)
                    }
                    for row in cur.fetchall()
                ]

            batch_rows = _process_batch(conn, papers, batch_theorems, similarity_threshold)

            if batch_rows:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM theorem_dependency
                        WHERE interpaper IS TRUE
                            AND src_theorem_id::TEXT = ANY(%s)
                        """,
                        (list({row["src_theorem_id"] for row in batch_rows}),)
                    )

                upsert_rows(conn, table="theorem_dependency", rows=batch_rows)
                conn.commit()

            pbar.update(len(papers))

if __name__ == "__main__":
    connect_interpaper_dependencies(batch_size=16, similarity_threshold=0.8)