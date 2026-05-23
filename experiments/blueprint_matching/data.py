"""RDS loaders for the lean-field blueprint-matching benchmark.

Ground-truth pairs are derived from ``informal_metadata.lean``: each informal
statement is paired with every formal statement whose ``decl_name`` appears
in the (possibly comma-separated) ``lean`` field. Both sides are global —
the informal pool is every informal statement with a non-null ``lean`` and a
slogan; the formal pool is every formal statement with a slogan, regardless
of which paper it belongs to.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Set, Tuple

import numpy as np

from rds.utils.connect import get_rds_connection


@dataclass
class InformalStmt:
    statement_id: str
    slogan_id:    str
    lean: str       # raw informal_metadata.lean value (may be "decl_a, decl_b")
    slogan: str


@dataclass
class FormalStmt:
    statement_id: str
    slogan_id:    str
    decl_name: str
    slogan: str


def fetch_informal(conn) -> List[InformalStmt]:
    """Every informal statement with a non-null ``lean`` and at least one
    non-insufficient slogan. Earliest slogan per statement wins (matches the
    apap experiment's tie-break)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (s.statement_id)
                   s.statement_id, sl.slogan_id, im.lean, sl.slogan
              FROM statement s
              JOIN informal_metadata im ON im.statement_id = s.statement_id
              JOIN slogan sl            ON sl.statement_id = s.statement_id
             WHERE im.lean IS NOT NULL
               AND NOT sl.insufficient_context
             ORDER BY s.statement_id, sl.created_at
            """
        )
        return [
            InformalStmt(statement_id=str(sid), slogan_id=str(slid), lean=lean, slogan=slogan)
            for sid, slid, lean, slogan in cur.fetchall()
        ]


def fetch_formal(conn) -> List[FormalStmt]:
    """Every formal statement with a non-insufficient slogan. The benchmark
    assumes one slogan per formal; DISTINCT ON keeps things safe if that
    invariant ever drifts (earliest created_at wins)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (s.statement_id)
                   s.statement_id, sl.slogan_id, fm.decl_name, sl.slogan
              FROM statement s
              JOIN formal_metadata fm ON fm.statement_id = s.statement_id
              JOIN slogan sl          ON sl.statement_id = s.statement_id
             WHERE NOT sl.insufficient_context
             ORDER BY s.statement_id, sl.created_at
            """
        )
        return [
            FormalStmt(statement_id=str(sid), slogan_id=str(slid), decl_name=decl, slogan=slogan)
            for sid, slid, decl, slogan in cur.fetchall()
        ]


def fetch_embeddings(
    conn,
    slogan_ids: List[str],
    embedding_model: str,
) -> Dict[str, np.ndarray]:
    """Return {slogan_id: vector} for embeddings present in the DB. Missing
    slogan_ids are omitted — callers should be prepared to drop them."""
    if not slogan_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT slogan_id, embedding
              FROM embedding
             WHERE slogan_id   = ANY(%s::uuid[])
               AND model_name  = %s
            """,
            ([str(s) for s in slogan_ids], embedding_model),
        )
        out: Dict[str, np.ndarray] = {}
        for sid, emb in cur.fetchall():
            # pgvector returns its text format "[v1,v2,...]" without an
            # adapter registered. Parse to float32 ndarray.
            if isinstance(emb, str):
                vec = np.fromstring(emb[1:-1], sep=",", dtype=np.float32)
            else:
                vec = np.asarray(emb, dtype=np.float32)
            out[str(sid)] = vec
        return out


def _split_lean(value: str) -> List[str]:
    return [t.strip() for t in value.split(",") if t.strip()]


def build_ground_truth(
    informal: List[InformalStmt],
    formal: List[FormalStmt],
) -> Set[Tuple[str, str]]:
    """For each informal, split ``lean`` on comma; every token that matches
    any formal's ``decl_name`` adds a ground-truth pair. If a decl_name
    appears on multiple formal statements (shouldn't, but allowed), each is
    counted as a valid match."""
    formals_by_decl: Dict[str, List[str]] = {}
    for f in formal:
        formals_by_decl.setdefault(f.decl_name, []).append(f.statement_id)

    truth: Set[Tuple[str, str]] = set()
    for im in informal:
        for tok in _split_lean(im.lean):
            for fid in formals_by_decl.get(tok, []):
                truth.add((im.statement_id, fid))
    return truth


def load_all() -> Tuple[List[InformalStmt], List[FormalStmt], Set[Tuple[str, str]]]:
    """Convenience: open a connection, pull both pools, build ground truth."""
    conn = get_rds_connection("v2")
    informal = fetch_informal(conn)
    formal   = fetch_formal(conn)
    truth    = build_ground_truth(informal, formal)
    return informal, formal, truth
