"""RDS writer for nl_fl_match_pilot.

Idempotent: re-running a (query_id, direction, exclusion, rank,
embedding_model) tuple overwrites the prior row via ON CONFLICT. So callers
can replay a stuck batch without worrying about duplicates.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

from psycopg2.extras import execute_values

from .topk import TopKResult


_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def ensure_table(conn) -> None:
    """Create the table + indexes if they don't exist. Safe to call repeatedly."""
    ddl = _SCHEMA_PATH.read_text()
    with conn.cursor() as cur:
        cur.execute(ddl)
    conn.commit()


_INSERT_SQL = """
INSERT INTO nl_fl_match_pilot (
    query_statement_id, direction, exclusion, rank,
    candidate_statement_id, candidate_paper_id,
    similarity, embedding_model, pool_descriptor
) VALUES %s
ON CONFLICT (query_statement_id, direction, exclusion, rank, embedding_model)
DO UPDATE SET
    candidate_statement_id = EXCLUDED.candidate_statement_id,
    candidate_paper_id     = EXCLUDED.candidate_paper_id,
    similarity             = EXCLUDED.similarity,
    pool_descriptor        = EXCLUDED.pool_descriptor,
    created_at             = now()
"""


def write_rows(
    conn,
    results: Iterable[TopKResult],
    *,
    direction: str,
    exclusion: str,
    pool_descriptor: str,
    embedding_model: str,
    batch_size: int = 500,
) -> int:
    """Bulk upsert. Returns the row count written."""
    valid_directions = {"f2i", "i2f", "f2f", "i2i"}
    valid_exclusions = {"statement", "paper"}
    if direction not in valid_directions:
        raise ValueError(f"direction must be one of {valid_directions}, got {direction!r}")
    if exclusion not in valid_exclusions:
        raise ValueError(f"exclusion must be one of {valid_exclusions}, got {exclusion!r}")

    batch: List[tuple] = []
    written = 0

    def _flush(cur):
        nonlocal batch, written
        if not batch:
            return
        execute_values(cur, _INSERT_SQL, batch, page_size=batch_size)
        written += len(batch)
        batch = []

    # psycopg2 is transactional by default; one transaction wraps the
    # whole batch and commits at the end.
    with conn.cursor() as cur:
        for r in results:
            batch.append((
                r.query_statement_id, direction, exclusion, r.rank,
                r.candidate_statement_id, r.candidate_paper_id,
                r.similarity, embedding_model, pool_descriptor,
            ))
            if len(batch) >= batch_size:
                _flush(cur)
        _flush(cur)
    conn.commit()
    return written


def clear_run(
    conn,
    *,
    direction: str,
    exclusion: str,
    embedding_model: str,
    pool_descriptor: str | None = None,
) -> int:
    """Wipe a prior run before re-running. Returns rows deleted."""
    where = ["direction = %s", "exclusion = %s", "embedding_model = %s"]
    params: list = [direction, exclusion, embedding_model]
    if pool_descriptor is not None:
        where.append("pool_descriptor = %s")
        params.append(pool_descriptor)
    sql = f"DELETE FROM nl_fl_match_pilot WHERE {' AND '.join(where)}"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        n = cur.rowcount
    conn.commit()
    return n


def count_rows(conn, **filters) -> int:
    """Small introspection helper. ``filters`` keys are column names."""
    if not filters:
        sql = "SELECT count(*) FROM nl_fl_match_pilot"
        params: list = []
    else:
        clauses = [f"{col} = %s" for col in filters]
        sql = f"SELECT count(*) FROM nl_fl_match_pilot WHERE {' AND '.join(clauses)}"
        params = list(filters.values())
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()[0]
