"""Formal-side context builder for slogan generation.

Mirrors prompt_utils.fetch_contexts but for formal statements: pulls the
target's ``statement + formal_metadata`` row, ranks its outgoing
``formal_dependency`` edges by the priority model from CONTEXT_DESIGN, packs
the highest-priority dependency blocks into a character budget, and returns
a context dict the prompt template can render as-is.

Priority tiers (highest → lowest):
    sig (in stated body)   105 (+ cross-module bonus)
    extends / field         50 (+ bonus)
    proof / def             20 (+ bonus; instances capped at 8; plumbing skipped)
    sig (elaboration artifact, not in stated body)   15
    docref                   5

Filters:
    - Skip deps whose target has in_degree ≥ _SKIP_INDEGREE (universally known).
    - Skip proof/def deps whose target module is logic/kernel plumbing.
    - For ubiquitous targets (20k ≤ in_degree < 30k) the description is
      truncated to one sentence.

Template contract: the formal Jinja template receives
    target           — dict with the target's fields
    target_block     — pre-rendered string block for the target declaration
    deps_text        — pre-rendered "----...----\nblock\n\n----...----\nblock"
                       string with as many deps as fit in the budget
    deps_included    — int, number of deps that made it into deps_text
    deps_available   — int, total ranked dep count (after filtering)
    budget           — int, the char budget used
    paper            — dict with paper.title etc. (Lean Repo slug etc.)
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple

from psycopg2.extensions import connection


# ---------------------------------------------------------------------------
# Tunable thresholds (mirrors CONTEXT_DESIGN.txt)
# ---------------------------------------------------------------------------

_SKIP_INDEGREE       = 30_000   # nodes above this: omit entirely
_UBIQUITOUS_INDEGREE = 20_000   # nodes above this: truncate description to one sentence
_INSTANCE_CAP        = 8        # proof/def-tier instance deps capped at this
_DEFAULT_BUDGET      = 4_000    # used if a formal template lacks {# budget: N #}

# Modules whose proof/def deps are pure proof-term plumbing.
_LOGIC_PLUMBING_PREFIXES = (
    "Init.Prelude",
    "Init.Core",
    "Init.Classical",
    "Init.SimpLemmas",
    "Init.Omega",
    "Lean.",
    "Std.Tactic",
    "Std.Sat",
)


def _is_logic_plumbing(module: str | None) -> bool:
    if not module:
        return False
    return any(
        module == p or module.startswith(p + ".") or module.startswith(p)
        for p in _LOGIC_PLUMBING_PREFIXES
    )


# ---------------------------------------------------------------------------
# Edge priority
# ---------------------------------------------------------------------------

_SIG_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9.]*")


def _sig_tokens(stated_body: str | None) -> set[str]:
    if not stated_body:
        return set()
    return set(_SIG_TOKEN_RE.findall(stated_body))


def _module_distance_bonus(target_module: str | None, dep_module: str | None) -> int:
    """0..6 bonus for cross-module deps. Tiebreaker within a tier."""
    if not target_module or not dep_module or target_module == dep_module:
        return 0
    t = target_module.split(".")
    d = dep_module.split(".")
    shared = sum(1 for a, b in zip(t, d) if a == b)
    return max(len(t), len(d)) - shared


def _edge_priority(edge: Dict[str, Any], sig_tokens: set[str]) -> int:
    """Base priority before the module bonus / instance cap / plumbing filter.
    Mirrors lean-graph/scripts/CONTEXT_DESIGN.txt:
      sig conclusion           → 100 + 10  (+1 if role='fn')
      sig hyp explicit         → 100 +  6  (+1 if role='fn')
      sig hyp inst             → 100 +  4  (+1 if role='fn')
      sig hyp implicit         → 100 +  2  (+1 if role='fn')
      sig hyp strict           → 100 +  0  (+1 if role='fn')
      sig elaboration artifact →  15
      extends / field          →  50
      proof / def              →  20
      docref                   →   5
    """
    etype = edge.get("edge_type", "")
    if etype == "sig":
        target    = edge.get("decl_name") or ""
        last_comp = target.rsplit(".", 1)[-1]
        # Elaboration artifact: name doesn't appear in stated signature → demote below proof/def.
        if target not in sig_tokens and last_comp not in sig_tokens:
            return 15
        if edge.get("position") == "conclusion":
            pos_score = 10
        else:
            pos_score = {"explicit": 6, "inst": 4, "implicit": 2, "strict": 0}.get(
                edge.get("binder") or "", 0
            )
        role_score = 1 if edge.get("role") == "fn" else 0
        return 100 + pos_score + role_score
    if etype in ("extends", "field"):
        return 50
    if etype in ("proof", "def"):
        return 20
    if etype == "docref":
        return 5
    return 0


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_SEP = "-" * 40


def _short_description(
    *,
    docstring: str | None,
    slogan: str | None,
    in_degree: int,
    is_target: bool,
) -> str:
    """Slogan beats docstring; ubiquitous (non-target) nodes get one sentence."""
    if slogan:
        return slogan.strip()
    if not docstring:
        return ""
    doc = docstring.strip()
    if is_target or in_degree < _UBIQUITOUS_INDEGREE:
        return doc
    m = re.search(r"\.(\s|$)", doc)
    return doc[:m.end()].strip() if m else doc[:120].strip()


def _format_target(target: Dict[str, Any]) -> str:
    desc = _short_description(
        docstring=target.get("docstring"),
        slogan=target.get("slogan"),
        in_degree=target.get("in_degree", 0),
        is_target=True,
    )
    lines = [
        "=" * 60,
        f"Declaration: {target.get('decl_name') or '<unknown>'}",
    ]
    if target.get("kind"):
        lines.append(f"Type:        {target['kind']}")
    if target.get("module"):
        lines.append(f"Module:      {target['module']}")
    lines.append("=" * 60)
    if desc:
        label = "Slogan" if target.get("slogan") else "Docstring"
        lines.append(f"\n{label}:\n{desc}")
    if target.get("body"):
        lines.append(f"\nSignature:\n{target['body']}")
    return "\n".join(lines)


def _format_dep(dep: Dict[str, Any]) -> str:
    desc = _short_description(
        docstring=dep.get("docstring"),
        slogan=dep.get("slogan"),
        in_degree=dep.get("in_degree", 0),
        is_target=False,
    )
    lines = [f"-- [{dep.get('kind') or '?'}] {dep.get('decl_name') or '<unknown>'}"]
    if desc:
        lines.append(f"-- {desc}")
    if dep.get("body"):
        lines.append(dep["body"])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Greedy budget packing
# ---------------------------------------------------------------------------

def _pack_deps(target_block: str, ranked_deps: List[Dict[str, Any]], budget: int) -> Tuple[str, int]:
    """Greedily add ranked dep blocks under the char budget. Returns
    (deps_text, n_included). The target_block is *not* deducted from the
    budget here — the caller's docstring of the contract says the budget
    covers the full output; we keep it simple and treat the budget as
    headroom for deps after the target. If you want the strict semantic,
    pass ``budget - len(target_block)`` in."""
    parts: List[str] = []
    used = 0
    join = "\n\n" + _SEP + "\n"
    for d in ranked_deps:
        block = _format_dep(d)
        addition = (join if parts else "") + block
        if used + len(addition) > budget:
            break
        parts.append(addition)
        used += len(addition)
    return "".join(parts), len(parts)


# ---------------------------------------------------------------------------
# SQL fetchers
# ---------------------------------------------------------------------------

def _fetch_targets(
    conn: connection,
    statement_ids: List[str],
) -> Dict[str, Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.statement_id, s.kind, s.body, s.proof,
                   fm.decl_name, fm.module, fm.file_path, fm.docstring,
                   p.paper_id, p.source, p.title, p.external_id, p.url, p.authors
              FROM statement s
              JOIN formal_metadata fm ON fm.statement_id = s.statement_id
              JOIN paper p            ON p.paper_id      = s.paper_id
             WHERE s.statement_id = ANY(%s::uuid[])
               AND s.formality   = 'formal'
            """,
            (statement_ids,),
        )
        cols = [c[0] for c in cur.description]
        out: Dict[str, Dict[str, Any]] = {}
        for row in cur.fetchall():
            r = dict(zip(cols, row))
            sid = str(r["statement_id"])
            out[sid] = {
                "statement_id": sid,
                "kind":         r["kind"],
                "body":         r["body"],
                "proof":        r["proof"],
                "decl_name":    r["decl_name"],
                "module":       r["module"],
                "file_path":    r["file_path"],
                "docstring":    r["docstring"],
                "paper": {
                    "paper_id":    str(r["paper_id"]),
                    "source":      r["source"],
                    "title":       r["title"],
                    "external_id": r["external_id"],
                    "url":         r["url"],
                    "authors":     r["authors"],
                },
            }
        return out


def _fetch_edges(conn: connection, src_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Edges with the dep's stmt + formal_metadata fields inlined.
    Returns {src_id: [dep_record, ...]}."""
    if not src_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT fd.src_id, fd.dep_id, fd.edge_type,
                   fd.position, fd.binder, fd.role, fd.via_proj,
                   dep_s.kind         AS dep_kind,
                   dep_s.body         AS dep_body,
                   dep_fm.decl_name   AS dep_decl_name,
                   dep_fm.module      AS dep_module,
                   dep_fm.docstring   AS dep_docstring,
                   dep_fm.is_instance AS dep_is_instance
              FROM formal_dependency fd
              JOIN statement dep_s        ON dep_s.statement_id = fd.dep_id
              JOIN formal_metadata dep_fm ON dep_fm.statement_id = fd.dep_id
             WHERE fd.src_id = ANY(%s::uuid[])
            """,
            (src_ids,),
        )
        cols = [c[0] for c in cur.description]
        out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in cur.fetchall():
            r = dict(zip(cols, row))
            out[str(r["src_id"])].append({
                "dep_id":      str(r["dep_id"]),
                "edge_type":   r["edge_type"],
                "position":    r["position"],
                "binder":      r["binder"],
                "role":        r["role"],
                "via_proj":    r["via_proj"],
                "kind":        r["dep_kind"],
                "body":        r["dep_body"],
                "decl_name":   r["dep_decl_name"],
                "module":      r["dep_module"],
                "docstring":   r["dep_docstring"],
                "is_instance": r["dep_is_instance"],
            })
        return dict(out)


def _fetch_in_degrees(conn: connection, dep_ids: Iterable[str]) -> Dict[str, int]:
    ids = list(set(dep_ids))
    if not ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT dep_id, COUNT(*) AS n
              FROM formal_dependency
             WHERE dep_id = ANY(%s::uuid[])
             GROUP BY dep_id
            """,
            (ids,),
        )
        return {str(sid): int(n) for sid, n in cur.fetchall()}


def _fetch_slogans(
    conn: connection,
    statement_ids: Iterable[str],
    prompt_name: str,
) -> Dict[str, str]:
    """Earliest non-insufficient slogan for each (statement_id, prompt_name)
    across any model. Empty dict if none exist yet."""
    ids = list(set(statement_ids))
    if not ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (statement_id) statement_id, slogan
              FROM slogan
             WHERE statement_id = ANY(%s::uuid[])
               AND prompt_name = %s
               AND NOT insufficient_context
             ORDER BY statement_id, created_at
            """,
            (ids, prompt_name),
        )
        return {str(sid): s for sid, s in cur.fetchall()}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

@dataclass
class FormalContextSpec:
    prompt_name: str
    budget: int


def fetch_formal_contexts(
    conn: connection,
    statement_ids: List[str],
    spec: FormalContextSpec,
) -> Dict[str, Dict[str, Any]]:
    """Build the template-ready context dict for each statement_id.

    Single batch: one fetch per "thing" (targets, edges, in_degrees, slogans)
    regardless of how many ids are in the batch.
    """
    if not statement_ids:
        return {}

    targets   = _fetch_targets(conn, statement_ids)
    if not targets:
        return {}

    edges_by_src = _fetch_edges(conn, list(targets.keys()))

    all_dep_ids = {d["dep_id"] for ds in edges_by_src.values() for d in ds}
    in_deg      = _fetch_in_degrees(conn, all_dep_ids)
    slogans     = _fetch_slogans(
        conn,
        list(all_dep_ids) + list(targets.keys()),
        spec.prompt_name,
    )

    out: Dict[str, Dict[str, Any]] = {}
    for sid, target in targets.items():
        target["slogan"]    = slogans.get(sid)
        target["in_degree"] = in_deg.get(sid, 0)
        sig_tokens          = _sig_tokens(target.get("body"))

        # Rank deps, deduping (dep_id, edge_type) → keep highest-priority edge.
        ranked: Dict[str, Tuple[int, Dict[str, Any]]] = {}
        for e in edges_by_src.get(sid, []):
            dep_id     = e["dep_id"]
            if dep_id == sid:
                continue  # skip self-loops
            dep_module = e.get("module")
            n          = in_deg.get(dep_id, 0)
            if n >= _SKIP_INDEGREE:
                continue
            etype = e["edge_type"]
            if etype in ("proof", "def") and _is_logic_plumbing(dep_module):
                continue

            base = _edge_priority(e, sig_tokens)
            # Cap silently-synthesized instance edges below docref.
            # Use the is_instance boolean (Lean.Meta.isInstanceCore) — `kind` is
            # the surface decl kind, which is 'inst' (not 'instance') in lean-graph.
            if e.get("is_instance") and base < 100:
                base = min(base, _INSTANCE_CAP)
            score = base + _module_distance_bonus(target.get("module"), dep_module)

            cur = ranked.get(dep_id)
            if cur is None or score > cur[0]:
                ranked[dep_id] = (score, e)

        ranked_list = sorted(ranked.values(), key=lambda x: -x[0])
        ranked_deps = []
        for _, e in ranked_list:
            e2 = dict(e)
            e2["slogan"]    = slogans.get(e["dep_id"])
            e2["in_degree"] = in_deg.get(e["dep_id"], 0)
            ranked_deps.append(e2)

        target_block = _format_target(target)
        deps_text, n_inc = _pack_deps(target_block, ranked_deps, spec.budget)

        out[sid] = {
            "statement":      target,            # back-compat alias
            "target":         target,
            "target_block":   target_block,
            "deps_text":      deps_text,
            "deps_included":  n_inc,
            "deps_available": len(ranked_deps),
            "budget":         spec.budget,
            "paper":          target["paper"],
        }
    return out
