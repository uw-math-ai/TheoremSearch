"""Slogan pilot harness for apap.

For each decl in decls.txt, resolves the Lean name against the v2 corpus DB,
extracts the blueprint LaTeX statement that carries the matching \\lean{} tag,
builds the prompt under one of three CONTEXT_MODEs, and calls the Anthropic
API to produce a slogan.

Outputs JSONL to outputs/slogans_<mode>.jsonl.

Usage:
    export ANTHROPIC_API_KEY=...
    python pilot.py isolated
    python pilot.py slogan_context     # requires isolated/ already run
    python pilot.py code_context

Env overrides: DB, BLUEPRINT_DIR, MODEL.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get(
    "DB",
    ROOT / "formalized_graph_v2/data/generated/corpus_v2_mathlib_plus_v4.29.db",
))
BLUEPRINT_DIR = Path(os.environ.get(
    "BLUEPRINT_DIR",
    ROOT / "formalized_graph/data/formalization_projects/apap/blueprint/src/chapter",
))
MODEL = os.environ.get("MODEL", "claude-sonnet-4-6")
APAP_PROJECT = "apap"
MAX_DEPS = 6  # cap dependency context per decl

PROMPT_MD = (HERE / "PROMPT.md").read_text()


# ---------- DB helpers ----------

def connect() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    return con


def project_id(con, name: str) -> int:
    row = con.execute("SELECT id FROM projects WHERE name = ?", (name,)).fetchone()
    if not row:
        raise RuntimeError(f"project {name!r} not in DB")
    return row["id"]


def resolve_node(con, decl: str, apap_pid: int):
    """Try apap first (exact, then suffix), then any project (exact)."""
    cur = con.execute(
        "SELECT * FROM nodes WHERE project_id = ? AND full_name = ?",
        (apap_pid, decl),
    )
    row = cur.fetchone()
    if row:
        return row, "apap_exact"
    cur = con.execute(
        "SELECT * FROM nodes WHERE project_id = ? AND full_name LIKE ?",
        (apap_pid, f"%.{decl}"),
    )
    row = cur.fetchone()
    if row:
        return row, "apap_suffix"
    cur = con.execute("SELECT * FROM nodes WHERE full_name = ?", (decl,))
    row = cur.fetchone()
    if row:
        return row, "mathlib_exact"
    cur = con.execute("SELECT * FROM nodes WHERE full_name LIKE ?", (f"%.{decl}",))
    row = cur.fetchone()
    if row:
        return row, "mathlib_suffix"
    return None, "unresolved"


def dependencies(con, node_id: int, limit: int = MAX_DEPS):
    cur = con.execute(
        """
        SELECT n.full_name, n.kind, n.signature, n.docstring, e.edge_type
        FROM edges e JOIN nodes n ON n.id = e.target_id
        WHERE e.source_id = ? AND e.edge_type IN ('sig','def')
        ORDER BY CASE e.edge_type WHEN 'sig' THEN 0 ELSE 1 END
        LIMIT ?
        """,
        (node_id, limit),
    )
    return [dict(r) for r in cur.fetchall()]


# ---------- Blueprint extraction ----------

_LEAN_RE = re.compile(r"\\lean\{([^}]*)\}")


def load_blueprint_units() -> dict[str, str]:
    """Map decl_name -> LaTeX body of the smallest enclosing environment."""
    units: dict[str, str] = {}
    env_re = re.compile(
        r"\\begin\{(theorem|lemma|definition|proposition|corollary)\}"
        r"(.*?)\\end\{\1\}",
        re.DOTALL,
    )
    for tex in BLUEPRINT_DIR.glob("*.tex"):
        text = tex.read_text()
        for m in env_re.finditer(text):
            body = m.group(2)
            names: list[str] = []
            for lm in _LEAN_RE.finditer(body):
                for n in lm.group(1).split(","):
                    n = n.strip()
                    if n:
                        names.append(n)
            for n in names:
                units.setdefault(n, body.strip())
    return units


# ---------- Prompt building ----------

def build_prompt(decl: str, node: dict | None, blueprint: str | None,
                 mode: str, dep_block: str | None) -> str:
    sig = (node["signature"] if node else "(decl not resolved in DB)").strip()
    doc = (node["docstring"] if node and node["docstring"] else "(none)").strip()
    kind = node["kind"] if node else "unknown"

    parts = [PROMPT_MD, "\n---\n", "## Now generate a slogan for:\n"]
    parts.append("```")
    parts.append(f"PROJECT: apap")
    parts.append(f"DECL_NAME: {decl}")
    parts.append(f"KIND: {kind}")
    parts.append("SIGNATURE:")
    parts.append(sig)
    parts.append("DOCSTRING:")
    parts.append(doc)
    parts.append(f"CONTEXT_MODE: {mode}")
    if dep_block:
        parts.append("DEPENDENCIES:")
        parts.append(dep_block)
    parts.append("```")
    if blueprint:
        parts.append(
            "\n(For your reference — the human-written NL statement from the "
            "apap blueprint. Do NOT echo its phrasing; produce an independent FL "
            "slogan from the Lean signature.)\n"
        )
        parts.append("```latex")
        parts.append(blueprint)
        parts.append("```")
    parts.append(
        "\nRespond with exactly two lines: `SLOGAN: …` then `CONFIDENCE: …`."
    )
    return "\n".join(parts)


def dep_block_slogan(deps, prior_slogans: dict[str, str]) -> str:
    lines = []
    for d in deps:
        s = prior_slogans.get(d["full_name"], "(no prior slogan)")
        lines.append(f"- {d['full_name']} [slogan: \"{s}\"]")
    return "\n".join(lines)


def dep_block_code(deps) -> str:
    lines = []
    for d in deps:
        sig = (d["signature"] or "").strip().replace("\n", " ")
        if len(sig) > 240:
            sig = sig[:240] + "…"
        lines.append(f"- {d['full_name']} [signature: \"{sig}\"]")
    return "\n".join(lines)


# ---------- API ----------

def call_claude(prompt: str) -> str:
    import anthropic  # late import so --help works without the dep
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=MODEL,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def parse_response(text: str) -> tuple[str, str]:
    slogan, conf = "", ""
    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith("slogan:"):
            slogan = line.split(":", 1)[1].strip()
        elif line.lower().startswith("confidence:"):
            conf = line.split(":", 1)[1].strip().lower()
    return slogan, conf


# ---------- Main ----------

def load_prior_slogans() -> dict[str, str]:
    path = HERE / "outputs/slogans_isolated.jsonl"
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("slogan"):
            out[r["decl"]] = r["slogan"]
    return out


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "isolated"
    assert mode in {"isolated", "slogan_context", "code_context"}, mode
    dry_run = "--dry-run" in sys.argv

    decls = [
        ln.strip() for ln in (HERE / "decls.txt").read_text().splitlines()
        if ln.strip() and not ln.startswith("#")
    ]
    blueprint = load_blueprint_units()
    prior = load_prior_slogans() if mode == "slogan_context" else {}

    con = connect()
    apap_pid = project_id(con, APAP_PROJECT)

    out_path = HERE / f"outputs/slogans_{mode}.jsonl"
    out_path.parent.mkdir(exist_ok=True)
    fout = out_path.open("w")

    for decl in decls:
        node, resolution = resolve_node(con, decl, apap_pid)
        node_d = dict(node) if node else None
        bp = blueprint.get(decl)

        dep_block = None
        deps_used: list[str] = []
        if node and mode != "isolated":
            deps = dependencies(con, node["id"])
            deps_used = [d["full_name"] for d in deps]
            if mode == "slogan_context":
                dep_block = dep_block_slogan(deps, prior) if deps else None
            else:
                dep_block = dep_block_code(deps) if deps else None

        prompt = build_prompt(decl, node_d, bp, mode, dep_block)
        (HERE / "prompts").mkdir(exist_ok=True)
        (HERE / f"prompts/{mode}__{decl.replace('/', '_')}.txt").write_text(prompt)

        record = {
            "decl": decl,
            "mode": mode,
            "resolution": resolution,
            "deps_used": deps_used,
            "has_blueprint": bp is not None,
        }
        if dry_run:
            record["slogan"] = ""
            record["confidence"] = ""
        else:
            try:
                resp = call_claude(prompt)
                slogan, conf = parse_response(resp)
                record["slogan"] = slogan
                record["confidence"] = conf
                record["raw"] = resp
            except Exception as e:
                record["error"] = repr(e)
                record["slogan"] = ""
                record["confidence"] = ""

        fout.write(json.dumps(record, ensure_ascii=False) + "\n")
        fout.flush()
        print(f"[{mode}] {decl}  ({resolution})  -> {record.get('slogan','')[:80]}")

    fout.close()
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
