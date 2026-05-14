"""Temporary ingestion: load the apap pilot from ``data.json`` into RDS.

Run from the TheoremSearch root:

    python -m experiments.formal_graph.slogan_pilot.ingest_to_rds

Idempotent — re-running upserts everything. Fields that aren't in data.json
(file_path, module, toolchain, etc.) come through as NULL.

Order of operations:
  1. paper row for the apap Lean repo (source='Lean Graph')
  2. lean_graph_paper_metadata stub (mostly NULL)
  3. statement + formal_metadata rows, one per fl_node
  4. formal_dependency rows for fl_edges
  5. statement_formalization rows — joins blueprint statements to formal
     decls via lean_to_label → informal_metadata.label. Requires the apap
     blueprint to already exist (source='Lean Community').
  6. slogan rows — bulk-load the pilot's outputs/slogans_<mode>.jsonl into
     the slogan table, after registering three pilot prompts and one pilot
     model.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from psycopg2.extras import Json

from rds.utils.connect import get_rds_connection
from rds.utils.upsert import insert_rows_returning, upsert_row, upsert_rows


HERE = Path(__file__).resolve().parent
DATA_JSON = HERE / "data.json"
PROMPT_MD = HERE / "PROMPT.md"
SLOGANS_DIR = HERE / "outputs"

SOURCE = "Lean Graph"
PROJECT_NAME = "apap"
# The lean_community paper for the apap blueprint (scrape_lean_community
# would have created this via its `<owner>/<repo>` slug).
BLUEPRINT_EXTERNAL_ID = "YaelDillies/apap"

# Pilot slogan provenance (pilot.py uses Sonnet at max_tokens=600).
PILOT_MODEL_NAME    = "pilot-claude-sonnet-4-6"
PILOT_MODEL_ID      = "claude-sonnet-4-6"
PILOT_MAX_TOKENS    = 600
PILOT_MODES         = ("isolated", "slogan_context", "code_context")


def _get_or_create_paper(conn) -> str:
    """Upsert the project's paper row and return its paper_id."""
    upsert_row(
        conn,
        table="paper",
        row={
            "kind":        "lean_repo",
            "source":      SOURCE,
            "external_id": PROJECT_NAME,
            "title":       PROJECT_NAME,
            "authors":     [],
            "categories":  [],
            "updated_at":  datetime.now(timezone.utc),
        },
        on_conflict={
            "with":    ["source", "external_id"],
            "replace": ["title", "updated_at"],
        },
    )
    with conn.cursor() as cur:
        cur.execute(
            "SELECT paper_id FROM paper WHERE source = %s AND external_id = %s",
            (SOURCE, PROJECT_NAME),
        )
        return cur.fetchone()[0]


def _upsert_project_metadata(conn) -> None:
    upsert_row(
        conn,
        table="lean_graph_paper_metadata",
        row={"project_name": PROJECT_NAME},
        on_conflict={"with": ["project_name"]},  # DO NOTHING — preserve any data already there
    )


def _existing_decl_ids(conn, paper_id: str) -> dict[str, str]:
    """Map decl_name -> statement_id for statements already in this paper."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT fm.decl_name, s.statement_id
            FROM statement s
            JOIN formal_metadata fm ON fm.statement_id = s.statement_id
            WHERE s.paper_id = %s AND fm.decl_name IS NOT NULL
            """,
            (paper_id,),
        )
        return {decl: sid for decl, sid in cur.fetchall()}


def _insert_statements(conn, paper_id: str, fl_nodes: list[dict]) -> dict[str, str]:
    """Insert (or fetch) a statement + formal_metadata row per fl_node.
    Returns decl_name → statement_id covering every node in fl_nodes."""
    decl_to_id = _existing_decl_ids(conn, paper_id)
    new_nodes = [n for n in fl_nodes if n["full_name"] not in decl_to_id]
    if not new_nodes:
        return decl_to_id

    stmt_rows = [
        {
            "paper_id":  paper_id,
            "formality": "formal",
            "kind":      n["kind"],
            "body":      n["signature"] or None,
            "proof":     None,
        }
        for n in new_nodes
    ]
    new_ids = insert_rows_returning(
        conn,
        table="statement",
        rows=stmt_rows,
        returning="statement_id",
    )
    for n, sid in zip(new_nodes, new_ids):
        decl_to_id[n["full_name"]] = sid

    meta_rows = [
        {
            "statement_id": decl_to_id[n["full_name"]],
            "file_path":    None,    # not in data.json
            "decl_name":    n["full_name"],
            "module":       None,    # not in data.json
            "docstring":    n.get("docstring") or None,
        }
        for n in new_nodes
    ]
    upsert_rows(
        conn,
        table="formal_metadata",
        rows=meta_rows,
        on_conflict={
            "with":    ["statement_id"],
            "replace": ["decl_name", "docstring"],
        },
    )
    print(f"  statement: inserted {len(new_nodes)} new (total {len(decl_to_id)})")
    return decl_to_id


def _insert_dependencies(conn, fl_edges: list[dict], decl_to_id: dict[str, str]) -> int:
    rows = []
    skipped = 0
    for e in fl_edges:
        src = decl_to_id.get(e["source"])
        dep = decl_to_id.get(e["target"])
        if src is None or dep is None:
            skipped += 1
            continue
        rows.append({
            "src_id":    src,
            "dep_id":    dep,
            "edge_type": e["type"],
        })
    if rows:
        upsert_rows(
            conn,
            table="formal_dependency",
            rows=rows,
            on_conflict={"with": ["src_id", "dep_id", "edge_type"]},  # DO NOTHING
        )
    print(f"  formal_dependency: upserted {len(rows)} edges ({skipped} skipped — endpoint missing)")
    return len(rows)


def _insert_formalization_links(
    conn,
    lean_to_label: dict[str, str],
    bp_nodes: list[dict],
    decl_to_id: dict[str, str],
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT paper_id FROM paper "
            "WHERE source = 'Lean Community' AND external_id = %s",
            (BLUEPRINT_EXTERNAL_ID,),
        )
        row = cur.fetchone()
    if row is None:
        print(f"  statement_formalization: SKIPPED — no Lean Community paper "
              f"found for external_id={BLUEPRINT_EXTERNAL_ID!r}. Run "
              f"scrape_lean_community + parse_papers for the apap blueprint first.")
        return 0
    blueprint_paper_id = row[0]

    bp_node_by_label = {n["id"]: n for n in bp_nodes}
    labels_needed = list({lbl for lbl in lean_to_label.values()})

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT im.label, s.statement_id
            FROM statement s
            JOIN informal_metadata im ON im.statement_id = s.statement_id
            WHERE s.paper_id = %s AND im.label = ANY(%s)
            """,
            (blueprint_paper_id, labels_needed),
        )
        label_to_informal_id = {lbl: sid for lbl, sid in cur.fetchall()}

    rows = []
    missing_label = 0
    missing_decl = 0
    for decl, label in lean_to_label.items():
        informal_id = label_to_informal_id.get(label)
        formal_id   = decl_to_id.get(decl)
        if informal_id is None:
            missing_label += 1
            continue
        if formal_id is None:
            missing_decl += 1
            continue
        bp = bp_node_by_label.get(label, {})
        rows.append({
            "informal_statement_id": informal_id,
            "formal_statement_id":   formal_id,
            "methods":               ["blueprint"],
            "evidence":              Json({"blueprint": {"label": label, "chapter": bp.get("chapter")}}),
        })

    if rows:
        upsert_rows(
            conn,
            table="statement_formalization",
            rows=rows,
            on_conflict={
                "with": ["informal_statement_id", "formal_statement_id"],
                # Merge methods, merge evidence JSONB, bump updated_at.
                "update_expr": (
                    "methods = ARRAY(SELECT DISTINCT unnest(statement_formalization.methods || EXCLUDED.methods)), "
                    "evidence = COALESCE(statement_formalization.evidence, '{}'::jsonb) "
                    "         || COALESCE(EXCLUDED.evidence, '{}'::jsonb), "
                    "updated_at = now()"
                ),
            },
        )
    print(f"  statement_formalization: upserted {len(rows)} links "
          f"(skipped {missing_label} unmatched labels, {missing_decl} unmatched decls)")
    return len(rows)


def _register_pilot_prompts_and_model(conn) -> None:
    """Ensure slogan_prompt has one row per pilot mode and slogan_model has
    the pilot's Sonnet entry. All upserts DO NOTHING on conflict — if you've
    already registered these with different content, this won't overwrite."""
    prompt_template = PROMPT_MD.read_text() if PROMPT_MD.exists() else "[Pilot prompt — see experiments/formal_graph/slogan_pilot/PROMPT.md]"
    for mode in PILOT_MODES:
        upsert_row(
            conn,
            table="slogan_prompt",
            row={
                "name":     f"pilot-{mode}",
                "template": f"[Pilot mode: {mode}]\n\n{prompt_template}",
            },
            on_conflict={"with": ["name"]},
        )
    upsert_row(
        conn,
        table="slogan_model",
        row={
            "name":        PILOT_MODEL_NAME,
            "model":       PILOT_MODEL_ID,
            "temperature": None,
            "max_tokens":  PILOT_MAX_TOKENS,
        },
        on_conflict={"with": ["name"]},
    )


def _insert_slogans(conn, decl_to_id: dict[str, str]) -> int:
    """Load each outputs/slogans_<mode>.jsonl into the slogan table.
    Confidence='low' → insufficient_context=TRUE so the graph API treats it
    as low-quality; high/medium → FALSE so they're eligible to surface."""
    rows = []
    missing_decl = 0
    no_text      = 0
    for mode in PILOT_MODES:
        path = SLOGANS_DIR / f"slogans_{mode}.jsonl"
        if not path.exists():
            print(f"  {mode}: file not found at {path}, skipping")
            continue
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                stmt_id = decl_to_id.get(rec["decl"])
                if stmt_id is None:
                    missing_decl += 1
                    continue
                text = rec.get("slogan")
                if not text:
                    no_text += 1
                    continue
                rows.append({
                    "statement_id":         stmt_id,
                    "prompt_name":          f"pilot-{mode}",
                    "model_name":           PILOT_MODEL_NAME,
                    "slogan":               text,
                    "insufficient_context": rec.get("confidence") == "low",
                })

    if rows:
        upsert_rows(
            conn,
            table="slogan",
            rows=rows,
            on_conflict={
                "with":    ["statement_id", "prompt_name", "model_name"],
                "replace": ["slogan", "insufficient_context"],
            },
        )
    print(f"  slogan: upserted {len(rows)} rows "
          f"(skipped {missing_decl} unknown decls, {no_text} empty)")
    return len(rows)


def main() -> None:
    data = json.loads(DATA_JSON.read_text())
    conn = get_rds_connection("v2")

    print(f"[1/6] paper row for source={SOURCE!r} external_id={PROJECT_NAME!r}")
    paper_id = _get_or_create_paper(conn)
    print(f"  paper_id = {paper_id}")

    print(f"[2/6] lean_graph_paper_metadata stub")
    _upsert_project_metadata(conn)

    resolved_nodes = [n for n in data["fl_nodes"] if n.get("resolved")]
    skipped = len(data["fl_nodes"]) - len(resolved_nodes)
    print(f"[3/6] statement + formal_metadata ({len(resolved_nodes)} resolved fl_nodes, {skipped} unresolved skipped)")
    decl_to_id = _insert_statements(conn, paper_id, resolved_nodes)

    print(f"[4/6] formal_dependency ({len(data['fl_edges'])} fl_edges)")
    _insert_dependencies(conn, data["fl_edges"], decl_to_id)

    print(f"[5/6] statement_formalization ({len(data['lean_to_label'])} lean_to_label entries)")
    _insert_formalization_links(conn, data["lean_to_label"], data["bp_nodes"], decl_to_id)

    print(f"[6/6] slogans from {SLOGANS_DIR.name}/ ({len(PILOT_MODES)} modes)")
    _register_pilot_prompts_and_model(conn)
    _insert_slogans(conn, decl_to_id)

    conn.commit()
    print("Done.")


if __name__ == "__main__":
    main()
