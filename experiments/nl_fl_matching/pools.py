"""Query and candidate pools for the NL↔FL matching pilot.

Every query-side fetcher returns ``list[Stmt]`` with a stable shape so the
downstream ``topk`` module can stay pool-agnostic. Candidate pools are
expressed as named WHERE-clause fragments — registered in CANDIDATE_FILTERS
to keep SQL injection off the table (only named filters are valid).

Pool counts as of 2026-05-24 (db v2):

  project_formals       36,708   non-Mathlib / non-Batteries Lean Repo decls
  blueprint_informals    2,544   informals belonging to Lean Community blueprints
  all_informals      11,749,533  every sloganed+embedded informal statement
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Stmt:
    """Minimal projection sufficient to drive topk lookup + result writing."""
    statement_id: str
    paper_id: str
    slogan_id: str
    name: str           # decl_name for formal; "kind ref" for informal
    slogan: str


# ─── Query-side fetchers ────────────────────────────────────────────────── #

_PROJECT_FORMAL_SQL = """
WITH project_papers AS (
    SELECT paper_id FROM paper
     WHERE source = 'Lean Repo'
       AND external_id NOT LIKE 'Mathlib_%%'
       AND external_id NOT LIKE 'Batteries_%%'
)
SELECT DISTINCT ON (st.statement_id)
       st.statement_id::text, st.paper_id::text,
       sl.slogan_id::text, fm.decl_name, sl.slogan
  FROM statement st
  JOIN project_papers pp ON pp.paper_id = st.paper_id
  JOIN formal_metadata fm ON fm.statement_id = st.statement_id
  JOIN slogan sl ON sl.statement_id = st.statement_id
  JOIN embedding e ON e.slogan_id = sl.slogan_id
 WHERE NOT sl.insufficient_context
   AND e.model_name = %(model)s
 ORDER BY st.statement_id, sl.created_at
"""

_BLUEPRINT_INFORMAL_SQL = """
SELECT DISTINCT ON (st.statement_id)
       st.statement_id::text, st.paper_id::text,
       sl.slogan_id::text,
       initcap(st.kind) || COALESCE(' ' || im.ref, '') AS name,
       sl.slogan
  FROM statement st
  JOIN paper p ON p.paper_id = st.paper_id
  LEFT JOIN informal_metadata im ON im.statement_id = st.statement_id
  JOIN slogan sl ON sl.statement_id = st.statement_id
  JOIN embedding e ON e.slogan_id = sl.slogan_id
 WHERE st.formality = 'informal'
   AND p.source = 'Lean Community'
   AND NOT sl.insufficient_context
   AND e.model_name = %(model)s
 ORDER BY st.statement_id, sl.created_at
"""

# Random informal sample for the (2) i→f experiment. setseed makes the
# draw reproducible across runs given the same seed value.
_INFORMAL_SAMPLE_SQL = """
SELECT DISTINCT ON (st.statement_id)
       st.statement_id::text, st.paper_id::text,
       sl.slogan_id::text,
       initcap(st.kind) || COALESCE(' ' || im.ref, '') AS name,
       sl.slogan
  FROM statement st
  LEFT JOIN informal_metadata im ON im.statement_id = st.statement_id
  JOIN slogan sl ON sl.statement_id = st.statement_id
  JOIN embedding e ON e.slogan_id = sl.slogan_id
 WHERE st.formality = 'informal'
   AND NOT sl.insufficient_context
   AND e.model_name = %(model)s
 ORDER BY st.statement_id, sl.created_at, random()
 LIMIT %(n)s
"""


def _rows_to_stmts(rows) -> List[Stmt]:
    return [Stmt(*r) for r in rows]


def fetch_project_formals(conn, embedding_model: str = "qwen3-8b",
                          limit: Optional[int] = None) -> List[Stmt]:
    sql = _PROJECT_FORMAL_SQL + ("  LIMIT %(limit)s" if limit else "")
    with conn.cursor() as cur:
        cur.execute(sql, {"model": embedding_model, "limit": limit})
        return _rows_to_stmts(cur.fetchall())


def fetch_blueprint_informals(conn, embedding_model: str = "qwen3-8b",
                              limit: Optional[int] = None) -> List[Stmt]:
    sql = _BLUEPRINT_INFORMAL_SQL + ("  LIMIT %(limit)s" if limit else "")
    with conn.cursor() as cur:
        cur.execute(sql, {"model": embedding_model, "limit": limit})
        return _rows_to_stmts(cur.fetchall())


def fetch_informal_sample(conn, n: int, seed: float = 0.0,
                          embedding_model: str = "qwen3-8b") -> List[Stmt]:
    """Uniform random sample from the 11.7M informal pool. ``seed`` in
    [-1, 1] is forwarded to setseed() for reproducibility."""
    with conn.cursor() as cur:
        cur.execute("SELECT setseed(%s)", (max(-1.0, min(1.0, seed)),))
        cur.execute(_INFORMAL_SAMPLE_SQL,
                    {"model": embedding_model, "n": n})
        return _rows_to_stmts(cur.fetchall())


# ─── Candidate-pool filters (named registry) ────────────────────────────── #

# Each value is a SQL fragment that goes into the ranked CTE's WHERE clause.
# `st.*` refers to the candidate statement; `p.*` to its paper. See
# topk._TOPK_SQL for the surrounding query shape.

CANDIDATE_FILTERS: dict[str, str] = {
    "all_informals": "st.formality = 'informal'",

    "project_formals": (
        "st.formality = 'formal' "
        "AND st.paper_id IN ("
        "    SELECT paper_id FROM paper "
        "     WHERE source = 'Lean Repo' "
        "       AND external_id NOT LIKE 'Mathlib_%%' "
        "       AND external_id NOT LIKE 'Batteries_%%'"
        ")"
    ),

    "blueprint_informals": (
        "st.formality = 'informal' "
        "AND st.paper_id IN ("
        "    SELECT paper_id FROM paper WHERE source = 'Lean Community'"
        ")"
    ),
}
