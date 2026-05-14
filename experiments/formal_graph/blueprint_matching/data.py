"""RDS loaders for the apap blueprint-matching benchmark.

All three queries are scoped to apap on both sides — change the constants
below to retarget the experiment at a different project (you'd also need that
project's blueprint paper + lean_repo paper + slogans + statement_formalization
rows to exist in RDS).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

from rds.utils.connect import get_rds_connection


BLUEPRINT_SOURCE      = "Lean Community"
BLUEPRINT_EXTERNAL_ID = "YaelDillies/apap"
FORMAL_SOURCE         = "Lean Graph"
FORMAL_EXTERNAL_ID    = "apap"


@dataclass
class InformalStmt:
    statement_id: str
    label: str            # informal_metadata.label (the blueprint \label{...})
    slogan: str


@dataclass
class FormalStmt:
    statement_id: str
    decl_name: str
    slogans: Dict[str, str] = field(default_factory=dict)   # prompt_name → slogan text


def fetch_informal(conn) -> List[InformalStmt]:
    """One row per blueprint statement that has at least one non-insufficient
    slogan. If multiple exist for a statement, the earliest by ``created_at``
    wins — matches the graph API's existing tie-break."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (s.statement_id)
                   s.statement_id, im.label, sl.slogan
            FROM slogan sl
            JOIN statement s ON s.statement_id = sl.statement_id
            JOIN informal_metadata im ON im.statement_id = s.statement_id
            JOIN paper p ON p.paper_id = s.paper_id
            WHERE p.source = %s AND p.external_id = %s
              AND NOT sl.insufficient_context
            ORDER BY s.statement_id, sl.created_at
            """,
            (BLUEPRINT_SOURCE, BLUEPRINT_EXTERNAL_ID),
        )
        return [
            InformalStmt(statement_id=str(sid), label=label or "", slogan=slogan)
            for sid, label, slogan in cur.fetchall()
        ]


def fetch_formal(conn) -> List[FormalStmt]:
    """For each apap formal decl, gather every non-insufficient slogan keyed
    by ``prompt_name``. Decls with no slogans are omitted."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.statement_id, fm.decl_name, sl.prompt_name, sl.slogan
            FROM statement s
            JOIN formal_metadata fm ON fm.statement_id = s.statement_id
            JOIN slogan sl ON sl.statement_id = s.statement_id
            JOIN paper p ON p.paper_id = s.paper_id
            WHERE p.source = %s AND p.external_id = %s
              AND NOT sl.insufficient_context
            ORDER BY fm.decl_name, sl.prompt_name
            """,
            (FORMAL_SOURCE, FORMAL_EXTERNAL_ID),
        )
        by_id: Dict[str, FormalStmt] = {}
        for sid, decl, prompt, slogan in cur.fetchall():
            sid = str(sid)
            if sid not in by_id:
                by_id[sid] = FormalStmt(statement_id=sid, decl_name=decl)
            by_id[sid].slogans[prompt] = slogan
        return list(by_id.values())


def fetch_ground_truth(conn) -> Set[Tuple[str, str]]:
    """``(informal_statement_id, formal_statement_id)`` pairs flagged by the
    blueprint author via ``\\lean{}`` (methods contains 'blueprint'). Both
    endpoints are scoped to the apap project on the right source."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT sf.informal_statement_id, sf.formal_statement_id
            FROM statement_formalization sf
            JOIN statement informal_s ON informal_s.statement_id = sf.informal_statement_id
            JOIN paper    informal_p ON informal_p.paper_id     = informal_s.paper_id
            JOIN statement formal_s   ON formal_s.statement_id   = sf.formal_statement_id
            JOIN paper    formal_p   ON formal_p.paper_id       = formal_s.paper_id
            WHERE informal_p.source = %s AND informal_p.external_id = %s
              AND formal_p.source   = %s AND formal_p.external_id   = %s
              AND 'blueprint' = ANY(sf.methods)
            """,
            (BLUEPRINT_SOURCE, BLUEPRINT_EXTERNAL_ID,
             FORMAL_SOURCE, FORMAL_EXTERNAL_ID),
        )
        return {(str(iid), str(fid)) for iid, fid in cur.fetchall()}


def load_all() -> Tuple[List[InformalStmt], List[FormalStmt], Set[Tuple[str, str]]]:
    """Convenience: open a connection, pull everything, return (informal, formal, truth)."""
    conn = get_rds_connection("v2")
    return fetch_informal(conn), fetch_formal(conn), fetch_ground_truth(conn)
