"""Blueprint gold pair loader.

Mirrors experiments/blueprint_matching/data.py::build_ground_truth: split
informal_metadata.lean on ',' and intersect with formal_metadata.decl_name.
1,595 gold pairs / 1,308 distinct informals / 1,577 distinct formals
across the 21 Lean Community blueprint repos (as of 2026-05-24).

Both query-side stmt fetchers are restricted to the gold subset so the
headline-table sweeps stay narrow.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Set, Tuple

from .pools import Stmt


# Cluster I/O contention can make load_gold take minutes. Cache the result
# under the package so re-running runners/analyses is instant.
_CACHE_PATH = Path(__file__).parent / "_gold_cache.json"


@dataclass
class GoldPairs:
    """Container for the gold-pair set + per-side stmt rows.

    informals[i].statement_id appears as the first element in some pair iff
    i has at least one gold formal partner. Symmetric for formals.
    """
    informals: List[Stmt]                # 1,308 distinct
    formals:   List[Stmt]                # 1,577 distinct
    pairs:     Set[Tuple[str, str]]      # (informal_sid, formal_sid)

    @property
    def informal_to_gold_formals(self) -> Dict[str, Set[str]]:
        out: Dict[str, Set[str]] = {}
        for i, f in self.pairs:
            out.setdefault(i, set()).add(f)
        return out

    @property
    def formal_to_gold_informals(self) -> Dict[str, Set[str]]:
        out: Dict[str, Set[str]] = {}
        for i, f in self.pairs:
            out.setdefault(f, set()).add(i)
        return out


def _to_cache_blob(g: GoldPairs) -> dict:
    return {
        "informals": [asdict(s) for s in g.informals],
        "formals":   [asdict(s) for s in g.formals],
        "pairs":     sorted(list(g.pairs)),
    }


def _from_cache_blob(blob: dict) -> GoldPairs:
    return GoldPairs(
        informals=[Stmt(**s) for s in blob["informals"]],
        formals=  [Stmt(**s) for s in blob["formals"]],
        pairs={tuple(p) for p in blob["pairs"]},
    )


def load_gold(conn, embedding_model: str = "qwen3-8b",
              use_cache: bool = True) -> GoldPairs:
    """Pull every blueprint-annotated informal + every formal it points at,
    plus the (informal_sid, formal_sid) pair set. Only includes statements
    that have a sloganed + embedded representation under ``embedding_model``.

    Cached to ``_gold_cache.json`` next to this module so runners + analysis
    scripts don't re-pay the multi-minute DB cost. Delete the file or pass
    ``use_cache=False`` to force a refresh."""
    if use_cache and _CACHE_PATH.exists():
        try:
            blob = json.loads(_CACHE_PATH.read_text())
            if blob.get("embedding_model") == embedding_model:
                return _from_cache_blob(blob)
        except (json.JSONDecodeError, KeyError, TypeError):
            pass  # corrupt cache → re-fetch and overwrite

    # Informals carrying \lean{...} annotations, with a slogan + embedding.
    # Filter informal_metadata FIRST (only ~1,655 rows have a non-NULL lean)
    # so the downstream joins operate on a tiny set instead of the full 11.7M
    # sloganed-informal corpus.
    informal_sql = """
    WITH lean_im AS (
        SELECT statement_id, ref, lean
          FROM informal_metadata
         WHERE lean IS NOT NULL
    )
    SELECT DISTINCT ON (s.statement_id)
           s.statement_id::text, s.paper_id::text,
           sl.slogan_id::text,
           initcap(s.kind) || COALESCE(' ' || im.ref, '') AS name,
           sl.slogan, im.lean
      FROM lean_im im
      JOIN statement s ON s.statement_id = im.statement_id
      JOIN slogan sl   ON sl.statement_id = s.statement_id
      JOIN embedding e ON e.slogan_id = sl.slogan_id
     WHERE NOT sl.insufficient_context
       AND e.model_name = %s
     ORDER BY s.statement_id, sl.created_at
    """
    # Sloganed+embedded formals — but only ones whose decl_name is referenced
    # by at least one informal_metadata.lean annotation. The decl_name list
    # is passed in as a parameter, taking the formal-side join from 388k
    # rows to ~1,577. Built after the informal fetch lands so we know which
    # tokens to look up.
    formal_sql = """
    SELECT DISTINCT ON (s.statement_id)
           s.statement_id::text, s.paper_id::text,
           sl.slogan_id::text, fm.decl_name, sl.slogan
      FROM formal_metadata fm
      JOIN statement s ON s.statement_id = fm.statement_id
      JOIN slogan sl   ON sl.statement_id = s.statement_id
      JOIN embedding e ON e.slogan_id = sl.slogan_id
     WHERE fm.decl_name = ANY(%s)
       AND NOT sl.insufficient_context
       AND e.model_name = %s
     ORDER BY s.statement_id, sl.created_at
    """

    informal_rows: list = []
    informal_lean: Dict[str, str] = {}
    with conn.cursor() as cur:
        cur.execute(informal_sql, (embedding_model,))
        for sid, pid, slid, name, slogan, lean in cur.fetchall():
            informal_rows.append(Stmt(sid, pid, slid, name, slogan))
            informal_lean[sid] = lean

        # Collect every decl_name token referenced by any \lean{} annotation
        # — that's the only set of formals we care to fetch.
        decl_tokens = {
            tok.strip()
            for lean in informal_lean.values()
            for tok in lean.split(",")
            if tok.strip()
        }
        if not decl_tokens:
            return GoldPairs(informals=[], formals=[], pairs=set())

        cur.execute(formal_sql, (list(decl_tokens), embedding_model))
        formal_rows_all = cur.fetchall()

    # Index formals by decl_name (multi-map: same name across repo versions).
    by_decl: Dict[str, List[Stmt]] = {}
    for sid, pid, slid, decl, slogan in formal_rows_all:
        by_decl.setdefault(decl, []).append(Stmt(sid, pid, slid, decl, slogan))

    pairs: Set[Tuple[str, str]] = set()
    for inf in informal_rows:
        for tok in informal_lean[inf.statement_id].split(","):
            tok = tok.strip()
            if not tok:
                continue
            for fm in by_decl.get(tok, []):
                pairs.add((inf.statement_id, fm.statement_id))

    # Restrict each side to statements that appear in ≥1 gold pair.
    matched_inf_ids = {a for a, _ in pairs}
    matched_fml_ids = {b for _, b in pairs}
    informals = [r for r in informal_rows if r.statement_id in matched_inf_ids]
    fid_to_stmt = {sid: Stmt(sid, pid, slid, decl, slogan)
                   for sid, pid, slid, decl, slogan in formal_rows_all
                   if sid in matched_fml_ids}
    formals = list(fid_to_stmt.values())

    result = GoldPairs(informals=informals, formals=formals, pairs=pairs)
    if use_cache:
        blob = _to_cache_blob(result)
        blob["embedding_model"] = embedding_model
        _CACHE_PATH.write_text(json.dumps(blob))
    return result
