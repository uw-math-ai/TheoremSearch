"""Compute the candidate-level attribute table.

For every unformalized candidate (status ∈ {none, annotated_only} in
formalization_candidate_neighborhood), compute:

  - math_category               : derived from paper.categories or repo slug
  - distance_undirected         : shortest UNDIRECTED hop count to any
                                  interface node (capped at MAX_HOPS)
  - distance_prereq_to_cons     : shortest DIRECTED hop count from
                                  interface, traversing prerequisite →
                                  consequence edges. In our DB that is
                                  the edge dep_id → src_id (a formalized
                                  prereq u becomes interface; v that
                                  cites u is at distance 1; etc.).
                                  This matches the colleague's ν_A(v).
  - distance_cite_to_dep        : shortest DIRECTED hop count from
                                  interface following the other
                                  direction in our DB: src_id → dep_id.
  - nearest_interface_id        : the interface node that achieved
                                  distance_undirected
  - nearest_interface_kind      : 'resolved_annotation' | 'gold_unresolved'
                                  | 'embedding_match'
  - true_inference              : nearest_interface_kind != 'embedding_match'

Interface set = union of:
  - resolved: informals with informal_metadata.lean that resolves to an
    existing formal_metadata.decl_name
  - gold_unresolved: informals with informal_metadata.lean populated but
    not resolving
  - embedding_match: informals appearing as query_statement_id in
    nl_fl_match_pilot with rank=1 and similarity >= 0.85

Run:
    RDS_HOST=theorem-search.cluster-cx0ei6kq0qcn.us-west-2.rds.amazonaws.com \
        python3 -m experiments.nl_fl_matching.analysis.candidate_attributes
"""
from __future__ import annotations

import sys
import time
from collections import Counter, deque
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "rds"))

from utils.connect import get_rds_connection  # noqa: E402

MAX_HOPS = 5
EMBEDDING_MATCH_SIM_THRESHOLD = 0.85

# Hand-curated math category for Lean Community blueprint repos
# (their `paper.categories` is empty since they're not arXiv).
REPO_CATEGORY: dict[str, list[str]] = {
    "teorth/pfr":                                ["math.CO", "math.PR"],
    "RemyDegenne/brownian-motion":               ["math.PR"],
    "ImperialCollegeLondon/FLT":                 ["math.NT"],
    "fpvandoorn/carleson":                       ["math.CA"],
    "YaelDillies/toric":                         ["math.AG"],
    "YaelDillies/apap":                          ["math.CO"],
    "kbuzzard/ClassFieldTheory":                 ["math.NT"],
    "thefundamentaltheor3m/Sphere-Packing-Lean": ["math.MG"],
    "leanprover-community/sphere-eversion":      ["math.GT"],
    "Paul-Lez/PersistentDecomp":                 ["math.AT"],
    "vihdzp/combinatorial-games":                ["math.CO"],
    "YaelDillies/cam-combi":                     ["math.CO"],
    "YaelDillies/chandra-furst-lipton":          ["math.CO", "cs.CC"],
    "YaelDillies/forbidden-matrix":              ["math.CO"],
    "YaelDillies/gibbs-measure":                 ["math.PR"],
    "YaelDillies/misc-yd":                       ["math.CO"],
    "YaelDillies/add-combi":                     ["math.CO"],
    "leanprover-community/flt-regular":          ["math.NT"],
    "YijunYuan/HarderNarasimhan":                ["math.AG"],
    "AlexKontorovich/PrimeNumberTheoremAnd":     ["math.NT"],
    "leanprover-community/physlib":              ["physics.gen-ph"],
    "google-deepmind/formal-conjectures":        ["math.GM"],
    "leanprover/cslib":                          ["cs.PL"],
    "math-inc/Sphere-Packing-Lean":              ["math.MG"],
    "emilyriehl/infinity-cosmos":                ["math.CT"],
}

SCHEMA = """
DROP TABLE IF EXISTS candidate_attributes;
CREATE TABLE candidate_attributes (
    statement_id              UUID PRIMARY KEY,
    math_category             TEXT[] NOT NULL DEFAULT '{}',
    distance_undirected       SMALLINT,
    distance_prereq_to_cons   SMALLINT,
    distance_cite_to_dep      SMALLINT,
    nearest_interface_id      UUID,
    nearest_interface_kind    TEXT,
    true_inference            BOOLEAN,
    pass_rate                 REAL,
    attempts_to_pass          INT,
    sorry_trajectory          INT[],
    max_hops                  SMALLINT NOT NULL DEFAULT 5,
    computed_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_ca_distance_undirected      ON candidate_attributes (distance_undirected);
CREATE INDEX idx_ca_distance_prereq_to_cons  ON candidate_attributes (distance_prereq_to_cons);
CREATE INDEX idx_ca_nearest_interface_kind   ON candidate_attributes (nearest_interface_kind);
CREATE INDEX idx_ca_math_category            ON candidate_attributes USING gin (math_category);
"""


def fetch_candidates(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT neighbor_statement_id::text
              FROM formalization_candidate_neighborhood
             WHERE status IN ('none','annotated_only')
        """)
        return [r[0] for r in cur.fetchall()]


def fetch_interface_sets(conn):
    """Return (resolved, gold_unresolved, embedding_match) as sets of sids."""
    with conn.cursor() as cur:
        # Resolved: informals whose lean annotation resolves
        cur.execute("""
            WITH lean_im AS (
              SELECT im.statement_id,
                     regexp_split_to_table(im.lean, ',') AS raw_tok
                FROM informal_metadata im
               WHERE im.lean IS NOT NULL
            ), tokens AS (
              SELECT statement_id, btrim(raw_tok) AS tok FROM lean_im
            )
            SELECT DISTINCT t.statement_id::text
              FROM tokens t
              JOIN formal_metadata fm ON fm.decl_name = t.tok
             WHERE t.tok <> ''
        """)
        resolved = {r[0] for r in cur.fetchall()}

        # All gold (any lean annotation), gold_unresolved = gold - resolved
        cur.execute("""
            SELECT DISTINCT statement_id::text
              FROM informal_metadata
             WHERE lean IS NOT NULL AND length(btrim(lean)) > 0
        """)
        all_gold = {r[0] for r in cur.fetchall()}
        gold_unresolved = all_gold - resolved

        # Embedding-match: informals appearing as queries in pilot
        cur.execute("""
            SELECT DISTINCT query_statement_id::text
              FROM nl_fl_match_pilot
             WHERE direction = 'i2f' AND rank = 1 AND similarity >= %s
        """, (EMBEDDING_MATCH_SIM_THRESHOLD,))
        embed_match = {r[0] for r in cur.fetchall()}
        # Strip embed_match entries that are already resolved or gold_unresolved —
        # source priority: resolved > gold_unresolved > embedding_match.
        embed_match = embed_match - resolved - gold_unresolved

    return resolved, gold_unresolved, embed_match


def fetch_categories_for(conn, sids):
    """Return {sid: (categories: list[str], repo_slug: str|None)}."""
    if not sids:
        return {}
    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.statement_id::text, p.categories, p.external_id
              FROM statement s JOIN paper p ON p.paper_id = s.paper_id
             WHERE s.statement_id = ANY(%s::uuid[])
        """, (list(sids),))
        out = {}
        for sid, cats, repo in cur.fetchall():
            cats = list(cats) if cats else []
            if not cats and repo in REPO_CATEGORY:
                cats = REPO_CATEGORY[repo]
            out[sid] = (cats, repo)
        return out


def fetch_adjacency(conn):
    """Return (users_of, deps_of) where edge in DB is src cites dep.
        users_of[dep] = list of src   (i.e., who depends on `dep`)
        deps_of[src]  = list of dep   (i.e., what `src` depends on)
    """
    users_of: dict[str, list[str]] = {}
    deps_of: dict[str, list[str]] = {}
    with conn.cursor(name="edge_cursor") as cur:
        cur.itersize = 200_000
        cur.execute("""
            SELECT src_id::text, dep_id::text
              FROM informal_dependency
             WHERE dep_id IS NOT NULL
        """)
        for s, d in cur:
            users_of.setdefault(d, []).append(s)
            deps_of.setdefault(s, []).append(d)
    return users_of, deps_of


def bfs(adj, sources, targets, max_hops):
    """Multi-source BFS over `adj`. Returns {target_sid: (distance, nearest_source)}."""
    source_set = set(sources)
    target_set = set(targets)
    out: dict[str, tuple[int, str]] = {t: (0, t) for t in target_set & source_set}
    visited: dict[str, str] = {s: s for s in source_set}
    frontier = deque(source_set)
    depth = 0
    remaining = target_set - source_set
    while frontier and depth < max_hops and remaining:
        depth += 1
        next_frontier = deque()
        for _ in range(len(frontier)):
            u = frontier.popleft()
            for v in adj.get(u, ()):
                if v in visited:
                    continue
                visited[v] = visited[u]
                next_frontier.append(v)
                if v in target_set:
                    out[v] = (depth, visited[u])
                    remaining.discard(v)
        frontier = next_frontier
    return out


def classify_kind(sid, resolved, gold_unresolved, embed_match):
    if sid in resolved: return "resolved_annotation"
    if sid in gold_unresolved: return "gold_unresolved"
    if sid in embed_match: return "embedding_match"
    return None


def main():
    conn = get_rds_connection("v2")

    t = time.time()
    print("[1/6] candidates", flush=True)
    cands = fetch_candidates(conn)
    print(f"      {len(cands)}", flush=True)

    t = time.time()
    print("[2/6] interface sets", flush=True)
    resolved, gold_unresolved, embed_match = fetch_interface_sets(conn)
    print(f"      resolved:        {len(resolved)}", flush=True)
    print(f"      gold_unresolved: {len(gold_unresolved)}", flush=True)
    print(f"      embed_match:     {len(embed_match)}", flush=True)
    print(f"      elapsed: {time.time()-t:.1f}s", flush=True)
    interface = resolved | gold_unresolved | embed_match

    t = time.time()
    print("[3/6] adjacency (~18M edges)", flush=True)
    users_of, deps_of = fetch_adjacency(conn)
    print(f"      users_of keys: {len(users_of)}  deps_of keys: {len(deps_of)}", flush=True)
    print(f"      elapsed: {time.time()-t:.1f}s", flush=True)

    # Undirected adjacency for the third BFS — synthesize from users_of + deps_of
    undirected: dict[str, list[str]] = {}
    for u, vs in users_of.items():
        undirected.setdefault(u, []).extend(vs)
    for u, vs in deps_of.items():
        undirected.setdefault(u, []).extend(vs)

    t = time.time()
    print("[4/6] BFS x3 (undirected, prereq→consequence, cite→prereq)", flush=True)
    dist_undir  = bfs(undirected, interface, cands, MAX_HOPS)
    dist_pre2c  = bfs(users_of, interface, cands, MAX_HOPS)   # interface u → users (consequences) v
    dist_cite2p = bfs(deps_of, interface, cands, MAX_HOPS)    # interface u → its prereqs v
    print(f"      undir:  {len(dist_undir)}/{len(cands)} reached", flush=True)
    print(f"      p2c:    {len(dist_pre2c)}/{len(cands)} reached", flush=True)
    print(f"      c2p:    {len(dist_cite2p)}/{len(cands)} reached", flush=True)
    print(f"      elapsed: {time.time()-t:.1f}s", flush=True)

    t = time.time()
    print("[5/6] categories for candidates + nearest-interface nodes", flush=True)
    cand_meta = fetch_categories_for(conn, cands)
    nearest_ids = {sid: dist_undir[sid][1] for sid in dist_undir}
    iface_meta = fetch_categories_for(conn, set(nearest_ids.values()))  # only for repo lookup later (unused now)
    print(f"      elapsed: {time.time()-t:.1f}s", flush=True)

    print("[6/6] writing to RDS", flush=True)
    rows = []
    for sid in cands:
        cats, _repo = cand_meta.get(sid, ([], None))
        undir_d, undir_src = dist_undir.get(sid, (None, None))
        p2c_d, _   = dist_pre2c.get(sid, (None, None))
        c2p_d, _   = dist_cite2p.get(sid, (None, None))
        kind = classify_kind(undir_src, resolved, gold_unresolved, embed_match) if undir_src else None
        true_inf = (kind in ("resolved_annotation", "gold_unresolved")) if kind else None
        rows.append((sid, cats, undir_d, p2c_d, c2p_d, undir_src, kind, true_inf, MAX_HOPS))

    from psycopg2.extras import execute_values
    with conn.cursor() as cur:
        for stmt in SCHEMA.strip().split(";"):
            if stmt.strip():
                cur.execute(stmt + ";")
        conn.commit()
        execute_values(cur, """
            INSERT INTO candidate_attributes
              (statement_id, math_category,
               distance_undirected, distance_prereq_to_cons, distance_cite_to_dep,
               nearest_interface_id, nearest_interface_kind, true_inference, max_hops)
            VALUES %s
        """, rows, page_size=500)
    conn.commit()
    print(f"      wrote {len(rows)} rows to candidate_attributes", flush=True)

    # === SUMMARIES ===
    print("\n=== distance_undirected ===")
    print_dist(dist_undir, cands)
    print("\n=== distance_prereq_to_cons (colleague's ν_A) ===")
    print_dist(dist_pre2c, cands)
    print("\n=== distance_cite_to_dep ===")
    print_dist(dist_cite2p, cands)

    print("\n=== nearest_interface_kind ===")
    kinds = Counter()
    for sid in cands:
        ns = dist_undir.get(sid, (None, None))[1]
        kinds[classify_kind(ns, resolved, gold_unresolved, embed_match) if ns else "unreachable"] += 1
    for k, v in kinds.items():
        print(f"  {k:25s}  {v:5d}  ({v/len(cands):.1%})")

    print("\n=== math_category (top 10) ===")
    cat_count = Counter()
    for sid in cands:
        cats, _ = cand_meta.get(sid, ([], None))
        for c in cats:
            cat_count[c] += 1
        if not cats:
            cat_count["(none)"] += 1
    for c, n in cat_count.most_common(10):
        print(f"  {c:20s}  {n:5d}")


def print_dist(dmap, cands):
    bucket = Counter(d for d, _ in dmap.values())
    unreached = len(cands) - len(dmap)
    for d in sorted(bucket):
        print(f"  distance {d}:  {bucket[d]:5d}  ({bucket[d]/len(cands):5.1%})")
    print(f"  unreachable / >max:  {unreached:5d}  ({unreached/len(cands):5.1%})")


if __name__ == "__main__":
    main()
