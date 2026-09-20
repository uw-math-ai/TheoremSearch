"""Populate (or refresh) statement_search and build its indexes.

statement_search (rds/core/statement_search.sql) is derived data: one row
per searchable embedding with the /graph/embedding filter columns next to
the binary-quantized vector. Re-running the load is idempotent (upsert by
embedding_id), so it doubles as the refresh after ingesting papers or
updating paper metadata (e.g. citation counts).

Usage
-----
    # See what would be loaded; writes nothing.
    python rds/scripts/build_statement_search.py

    # Create the table (if needed) and load every paper, 2000 papers per batch.
    python rds/scripts/build_statement_search.py --load

    # Loading is I/O-bound (each row reads a 16KB vector); run disjoint
    # paper_id shards in parallel to use more of the storage bandwidth:
    python rds/scripts/build_statement_search.py --load --after 00000000-0000-0000-0000-000000000000 --before 40000000-0000-0000-0000-000000000000
    python rds/scripts/build_statement_search.py --load --after 40000000-0000-0000-0000-000000000000 --before 80000000-0000-0000-0000-000000000000
    ...

    # Refresh only some sources (e.g. after ingesting them).
    python rds/scripts/build_statement_search.py --load --source "Stacks Project" --source ProofWiki

    # Build the indexes once the initial load is done (hours for the arXiv
    # HNSW graph: run from EC2 and pre-scale ACUs, as for
    # build_embedding_hnsw_index.py).
    python rds/scripts/build_statement_search.py --indexes

Rows whose embedding/slogan/statement/paper is deleted go away via
ON DELETE CASCADE; rows whose slogan becomes insufficient_context are
removed by --load for the affected papers.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.connect import get_rds_connection

EMBED_MODEL = "qwen3-8b"
SLOGAN_MODELS = ["qwen3-235b"]

_DDL_PATH = os.path.join(os.path.dirname(__file__), "..", "core", "statement_search.sql")

_PAPER_BATCH_SQL = """
SELECT paper_id FROM paper
WHERE paper_id > %(after)s
  AND (%(before)s::uuid IS NULL OR paper_id < %(before)s::uuid)
  AND (%(sources)s::text[] IS NULL OR source = ANY(%(sources)s))
  AND source IS NOT NULL
ORDER BY paper_id
LIMIT %(batch)s
"""

# Replace the rows of one batch of papers.
_DELETE_SQL = "DELETE FROM statement_search WHERE paper_id = ANY(%(papers)s::uuid[])"
_INSERT_SQL = """
INSERT INTO statement_search (
    embedding_id, statement_id, paper_id, source, formality, kind,
    primary_category, year, in_journal, citation_count, external_id, bq
)
SELECT
    e.embedding_id,
    st.statement_id,
    p.paper_id,
    p.source,
    st.formality,
    search_kind(st.kind),
    p.categories[1],
    EXTRACT(YEAR FROM p.updated_at)::int,
    CASE WHEN apm.arxiv_id IS NULL THEN NULL ELSE apm.journal_ref IS NOT NULL END,
    apm.citation_count,
    lower(p.external_id),
    binary_quantize(e.embedding)::bit(4096)
FROM statement st
JOIN paper p      ON p.paper_id = st.paper_id
JOIN slogan s     ON s.statement_id = st.statement_id
JOIN embedding e  ON e.slogan_id = s.slogan_id
LEFT JOIN arxiv_paper_metadata apm ON apm.arxiv_id = p.external_id
WHERE st.paper_id = ANY(%(papers)s::uuid[])
  AND s.model_name = ANY(%(slogan_models)s)
  AND NOT s.insufficient_context
  AND e.model_name = %(model)s
"""

_COUNT_SQL = """
SELECT p.source, count(*) AS rows
FROM paper p
JOIN statement st ON st.paper_id = p.paper_id
JOIN slogan s     ON s.statement_id = st.statement_id
JOIN embedding e  ON e.slogan_id = s.slogan_id
WHERE s.model_name = ANY(%(slogan_models)s)
  AND NOT s.insufficient_context
  AND e.model_name = %(model)s
  AND (%(sources)s::text[] IS NULL OR p.source = ANY(%(sources)s))
GROUP BY 1 ORDER BY 2 DESC
"""

# Cheapest first: a long HNSW build that dies (e.g. a dropped client) rolls
# back only itself, leaving the rest committed. The big arXiv graph is last.
_INDEXES = [
    ("statement_search_statement", "(statement_id)"),
    ("statement_search_paper",     "(paper_id)"),
    ("statement_search_category",  "(primary_category)"),
    ("statement_search_year",      "(year)"),
    ("statement_search_citations", "(citation_count)"),
    ("statement_search_formal",    "(source) WHERE formality = 'formal'"),
    ("statement_search_kind",      "(kind)"),
    ("statement_search_bq_other_hnsw",
     "USING hnsw (bq bit_hamming_ops) WITH (m = 32, ef_construction = 256) WHERE source <> 'arXiv'"),
    ("statement_search_bq_arxiv_hnsw",
     "USING hnsw (bq bit_hamming_ops) WITH (m = 32, ef_construction = 256) WHERE source = 'arXiv'"),
]


def _ensure_table(conn) -> None:
    with open(_DDL_PATH, encoding="utf-8") as f, conn.cursor() as cur:
        cur.execute(f.read())


def load(db: str, sources: list[str] | None, batch: int,
         after: str | None = None, before: str | None = None) -> None:
    conn = get_rds_connection(db)
    conn.autocommit = False
    _ensure_table(conn)
    conn.commit()

    params = {"sources": sources, "batch": batch, "before": before,
              "model": EMBED_MODEL, "slogan_models": SLOGAN_MODELS}
    after = after or "00000000-0000-0000-0000-000000000000"
    n_papers = n_rows = 0
    t0 = time.perf_counter()
    while True:
        with conn.cursor() as cur:
            cur.execute(_PAPER_BATCH_SQL, {**params, "after": after})
            papers = [r[0] for r in cur.fetchall()]
            if not papers:
                break
            # The planner overestimates a batch by ~10x and switches to hash
            # joins over full scans of embedding/slogan/paper; a batch is
            # small, so pin it to index-driven nested loops.
            cur.execute("SET LOCAL enable_hashjoin = off")
            cur.execute("SET LOCAL enable_mergejoin = off")
            cur.execute(_DELETE_SQL, {"papers": papers})
            cur.execute(_INSERT_SQL, {**params, "papers": papers})
            n_rows += cur.rowcount
        conn.commit()
        n_papers += len(papers)
        after = papers[-1]
        rate = n_papers / (time.perf_counter() - t0)
        print(f"  {n_papers:>9,} papers  {n_rows:>11,} rows  ({rate:,.0f} papers/s)", flush=True)
    conn.close()
    print(f"Loaded {n_rows:,} rows from {n_papers:,} papers in {(time.perf_counter() - t0) / 60:.1f} min.")


def build_indexes(db: str, mem: str, workers: int) -> None:
    conn = get_rds_connection(db)
    conn.autocommit = True
    conn.notices[:] = []
    with conn.cursor() as cur:
        cur.execute(f"SET maintenance_work_mem = '{mem}'")
        cur.execute(f"SET max_parallel_maintenance_workers = {int(workers)}")
        # pgvector NOTICEs when the HNSW graph outgrows maintenance_work_mem
        # and falls back to the (much slower) on-disk build; surface it.
        cur.execute("SET client_min_messages = notice")
        for name, spec in _INDEXES:
            t0 = time.perf_counter()
            print(f"Building {name} ...", flush=True)
            cur.execute(f"CREATE INDEX IF NOT EXISTS {name} ON statement_search {spec}")
            for notice in conn.notices:
                print(f"    {notice.strip()}", flush=True)
            conn.notices[:] = []
            print(f"  done in {(time.perf_counter() - t0) / 60:.1f} min", flush=True)
        cur.execute("""CREATE STATISTICS IF NOT EXISTS statement_search_source_formality
                       (dependencies, mcv) ON source, formality, kind FROM statement_search""")
        cur.execute("ANALYZE statement_search")
    conn.close()


def dry_run(db: str, sources: list[str] | None) -> None:
    conn = get_rds_connection(db)
    conn.set_session(readonly=True)
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = 0")
        cur.execute(_COUNT_SQL, {"sources": sources, "model": EMBED_MODEL, "slogan_models": SLOGAN_MODELS})
        rows = cur.fetchall()
    conn.close()
    print("Rows --load would write (dry run; nothing written):")
    for source, n in rows:
        print(f"  {source:30s} {n:>12,}")
    print(f"  {'total':30s} {sum(n for _, n in rows):>12,}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default="v2")
    parser.add_argument("--load", action="store_true", help="Create the table if needed and (re)load rows.")
    parser.add_argument("--indexes", action="store_true", help="Build the indexes (after --load).")
    parser.add_argument("--source", action="append", dest="sources",
                        help="Only load papers from this source. Repeatable. Default: all.")
    parser.add_argument("--batch", type=int, default=2000, help="Papers per transaction. Default: 2000.")
    parser.add_argument("--after", help="Only papers with paper_id > this UUID (resume, or shard the load).")
    parser.add_argument("--before", help="Only papers with paper_id < this UUID (shard the load).")
    parser.add_argument("--maintenance-work-mem", default="8GB")
    parser.add_argument("--max-parallel-maintenance-workers", type=int, default=6)
    args = parser.parse_args()

    if not (args.load or args.indexes):
        dry_run(args.db, args.sources)
        return
    if args.load:
        load(args.db, args.sources, args.batch, args.after, args.before)
    if args.indexes:
        build_indexes(args.db, args.maintenance_work_mem, args.max_parallel_maintenance_workers)


if __name__ == "__main__":
    main()
