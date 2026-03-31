from __future__ import annotations

import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, render_template, request
from loguru import logger

# Ensure project root is in path
sys.path.append(os.getcwd())

import tex_parser

template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "templates"))
app = Flask(__name__, template_folder=template_dir)

DB_PATH = Path("formalized_graph/data/generated/global_corpus.db")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


PAPER_NODES: dict[str, Any] = {}
ACTIVE_PROJECT = "FLT"
LATEX_MACROS: dict[str, str] = {}


def extract_balanced(text: str, start_idx: int) -> tuple[str | None, int]:
    """Finds the content of the first balanced brace group starting after start_idx."""
    pos = text.find("{", start_idx)
    if pos == -1:
        return None, -1
    depth = 0
    res = []
    for i in range(pos, len(text)):
        if text[i] == "{":
            depth += 1
            if depth > 1:
                res.append("{")
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return "".join(res), i + 1
            res.append("}")
        elif depth > 0:
            res.append(text[i])
    return None, -1


def load_project_macros(project_name: str) -> None:
    global LATEX_MACROS
    base_path = Path(f"formalized_graph/data/formalization_projects/{project_name}")
    macro_path = base_path / "blueprint/src/macro/common.tex"
    if not macro_path.exists():
        LATEX_MACROS = {}
        return

    content = macro_path.read_text()
    content = re.sub(r"%.*$", "", content, flags=re.MULTILINE)  # Strip comments
    macros = {}

    # 1. Brace-aware \newcommand parser
    idx = 0
    while True:
        m = re.search(r"\\newcommand\{\\(\w+)\}", content[idx:])
        if not m:
            break
        name = m.group(1)
        def_start = idx + m.end()
        definition, next_idx = extract_balanced(content, def_start)
        if definition is not None:
            macros["\\" + name] = definition.strip()
            idx = next_idx
        else:
            idx += m.end()

    # 2. DeclareMathOperator parser
    for match in re.finditer(r"\\DeclareMathOperator\{\\(\w+)\}\{(.*?)\}", content):
        name, op = match.groups()
        macros["\\" + name] = f"\\operatorname{{{op}}}"

    LATEX_MACROS = macros
    logger.info(f"Loaded {len(macros)} custom LaTeX macros for {project_name}.")


def load_project_blueprint(project_name: str) -> None:
    global PAPER_NODES
    blueprint_path = Path(f"formalized_graph/data/formalization_projects/{project_name}/blueprint/src")
    if blueprint_path.exists():
        logger.info(f"Parsing blueprint for {project_name}...")
        PAPER_NODES = tex_parser.build_paper_graph(str(blueprint_path))
    else:
        PAPER_NODES = {}


@app.route("/")
def index() -> str:
    return render_template("index.html")


@app.route("/api/macros")
def api_macros() -> Response:
    return jsonify(LATEX_MACROS)


@app.route("/api/projects")
def api_projects() -> Response:
    db = get_db()
    rows = db.execute("SELECT name FROM projects WHERE is_mathlib = 0").fetchall()
    project_names = [r["name"] for r in rows]
    if ACTIVE_PROJECT not in project_names:
        project_names.append(ACTIVE_PROJECT)
    return jsonify({"projects": project_names, "active": ACTIVE_PROJECT})


@app.route("/api/stats")
def api_stats() -> Response:
    db = get_db()
    lean_nodes = db.execute("SELECT count(*) FROM nodes").fetchone()[0]
    mathlib_res = db.execute("SELECT id FROM projects WHERE name='Mathlib'").fetchone()
    mathlib_count = 0
    if mathlib_res:
        query = "SELECT count(*) FROM nodes WHERE project_id = ?"
        mathlib_count = db.execute(query, (mathlib_res["id"],)).fetchone()[0]

    lean_files = db.execute("SELECT count(DISTINCT file_path) FROM nodes").fetchone()[0]
    return jsonify(
        {
            "lean_nodes": lean_nodes,
            "lean_files": lean_files,
            "paper_nodes": len(PAPER_NODES),
            "mathlib_coverage": mathlib_count,
        }
    )


@app.route("/api/capstones")
def api_capstones() -> Response:
    caps: list[dict[str, Any]] = []
    db = get_db()
    for pid, pnode in PAPER_NODES.items():
        ln = pnode.get("lean_name")
        is_linked = False
        if ln and ln not in ["???", "TODO"]:
            query = "SELECT 1 FROM nodes WHERE full_name = ? OR full_name LIKE ?"
            row = db.execute(query, (ln, f"%{ln}%")).fetchone()
            is_linked = row is not None
        entry = {"id": pid, "label": pid, "type": "paper", "is_linked": is_linked}
        if is_linked:
            caps.insert(0, entry)
        else:
            caps.append(entry)
    return jsonify(caps[:40])


@app.route("/api/search")
def api_search() -> Response:
    q = request.args.get("q", "").lower()
    if not q:
        return jsonify([])
    db = get_db()
    elements: list[dict[str, Any]] = []
    added: set[str] = set()
    added_edges: set[tuple[str, str]] = set()

    def add_node(node_id: str) -> None:
        if node_id not in added:
            query = "SELECT full_name, file_path FROM nodes WHERE full_name = ?"
            row = db.execute(query, (node_id,)).fetchone()
            if row:
                label = row["full_name"].split(".")[-1]
                ntype = "mathlib" if "Mathlib" in row["file_path"] else "lean"
                elements.append(
                    {"data": {"id": node_id, "label": label, "type": ntype}}
                )
            elif node_id in PAPER_NODES:
                elements.append(
                    {"data": {"id": node_id, "label": node_id, "type": "paper"}}
                )
            added.add(node_id)

    def add_edge(source: str, target: str, etype: str | None = None) -> None:
        if source in added and target in added and (source, target) not in added_edges:
            edge = {"source": source, "target": target}
            if etype:
                edge["type"] = etype
            elements.append({"data": edge})
            added_edges.add((source, target))

    for pid, pnode in PAPER_NODES.items():
        if q in pid.lower() or q in pnode.get("title", "").lower():
            add_node(pid)
            ln = pnode.get("lean_name")
            if ln and ln not in ["???", "TODO"]:
                query = "SELECT full_name, id FROM nodes WHERE full_name = ? OR full_name LIKE ?"
                row = db.execute(query, (ln, f"%{ln}")).fetchone()
                if row:
                    real_ln = row["full_name"]
                    add_node(real_ln)
                    add_edge(pid, real_ln, "impl")
                    # ENFORCE DIRECT ONLY (is_implicit = 0)
                    q_deps = "SELECT n.full_name FROM nodes n JOIN edges e ON n.id = e.target_id WHERE e.source_id = ? AND e.is_implicit = 0 LIMIT 20"
                    deps = db.execute(q_deps, (row["id"],)).fetchall()
                    for d in deps:
                        add_node(d["full_name"])
                        add_edge(real_ln, d["full_name"])

    query_ln = "SELECT id, full_name FROM nodes WHERE full_name LIKE ? LIMIT 20"
    rows = db.execute(query_ln, (f"%{q}%",)).fetchall()
    for r in rows:
        ln_name = r["full_name"]
        add_node(ln_name)
        for pid, pnode in PAPER_NODES.items():
            if pnode.get("lean_name") == ln_name:
                add_node(pid)
                add_edge(pid, ln_name, "impl")
        # ENFORCE DIRECT ONLY (is_implicit = 0)
        q_deps = "SELECT n.full_name FROM nodes n JOIN edges e ON n.id = e.target_id WHERE e.source_id = ? AND e.is_implicit = 0 LIMIT 15"
        deps = db.execute(q_deps, (r["id"],)).fetchall()
        for d in deps:
            add_node(d["full_name"])
            add_edge(ln_name, d["full_name"])
    return jsonify(elements)


@app.route("/api/details")
def api_details() -> Response | tuple[Response, int]:
    node_id = request.args.get("id")
    if not node_id:
        return jsonify({"error": "Missing id"}), 400
    db = get_db()
    # Join with projects to get the repo URL
    row = db.execute(
        """
        SELECT n.*, p.url as repo_url, p.name as project_name 
        FROM nodes n
        JOIN projects p ON n.project_id = p.id
        WHERE n.full_name = ?
    """,
        (node_id,),
    ).fetchone()

    linked_papers: list[dict[str, Any]] = []

    # 1. If it's a paper node, add itself to the linked_papers list
    if node_id in PAPER_NODES:
        p = PAPER_NODES[node_id]
        linked_papers.append(
            {
                "id": node_id,
                "title": p.get("title"),
                "body": p.get("body"),
                "context": p.get("context"),
                "lean_link": p.get("lean_name")
            }
        )

    if row:
        # ENFORCE DIRECT ONLY FOR DEGREES
        in_deg = db.execute(
            "SELECT count(*) FROM edges WHERE target_id = ? AND is_implicit = 0", (row["id"],)
        ).fetchone()[0]
        out_deg = db.execute(
            "SELECT count(*) FROM edges WHERE source_id = ? AND is_implicit = 0", (row["id"],)
        ).fetchone()[0]
        
        # 1. Path & URL Resolution
        # The stored file_path might be absolute (Lean core) or relative (projects/mathlib)
        raw_path = row["file_path"] or ""
        clean_path = raw_path
        
        # Handle Lean Core (absolute paths to .elan)
        is_lean_core = "/.elan/toolchains/" in raw_path
        if is_lean_core:
            # Extract relative path from Lean core: .../lib/lean/Init/Prelude.lean -> Init/Prelude.lean
            if "lib/lean/" in raw_path:
                clean_path = raw_path.split("lib/lean/")[-1]
            repo_url = "https://github.com/leanprover/lean4"
            branch = "master" # Lean 4 core uses master/main depending on version, master is usually safe for stable
            source_url = f"{repo_url}/blob/{branch}/src/lean/{clean_path}"
        else:
            # Handle Projects (Mathlib, FLT, etc.)
            # Standardize path: remove build artifacts if present
            clean_path = raw_path.replace(".lake/build/ir/", "").replace("build/ir/", "")
            
            # If it's mathlib, it's often stored as data/mathlib/mathlib4/Mathlib/...
            # but on GitHub it's just Mathlib/...
            if "Mathlib/" in clean_path:
                clean_path = "Mathlib/" + clean_path.split("Mathlib/", 1)[-1]
            elif "data/formalization_projects/" in clean_path:
                # Strip data/formalization_projects/ProjectName/
                parts = clean_path.split("/")
                if len(parts) > 3:
                    clean_path = "/".join(parts[3:])
            
            repo_url = row["repo_url"].rstrip("/") if row["repo_url"] else None
            branch = "master" if repo_url and "mathlib4" in repo_url else "main"
            source_url = f"{repo_url}/blob/{branch}/{clean_path}" if repo_url else None

        # 2. Suffix-aware search for paper results linking to this Lean node
        for pid, pnode in PAPER_NODES.items():
            ln = pnode.get("lean_name")
            if ln and ln not in ["???", "TODO"]:
                if (
                    ln == node_id
                    or node_id.endswith("." + ln)
                    or ln.endswith("." + node_id)
                ):
                    # Prevent duplicates if already added as a paper node
                    if not any(lp["id"] == pid for lp in linked_papers):
                        linked_papers.append(
                            {
                                "id": pid,
                                "title": pnode.get("title"),
                                "body": pnode.get("body"),
                                "context": pnode.get("context"),
                            }
                        )

        # 3. Docs URL (Mathlib and Lean core are both in the mathlib docs)
        docs_url = None
        if "Mathlib" in row["project_name"] or is_lean_core:
            docs_url = f"https://leanprover-community.github.io/mathlib4_docs/find/?q={node_id}"

        return jsonify(
            {
                "doc": row["docstring"],
                "body": row["statement"],
                "file": clean_path,
                "in_degree": in_deg,
                "out_degree": out_deg,
                "is_verified": True,
                "linked_papers": linked_papers,
                "docs_url": docs_url,
                "source_url": source_url,
            }
        )

    if linked_papers:
        return jsonify({"linked_papers": linked_papers, "type": "paper"})

    return jsonify({"error": "Not found"}), 404


if __name__ == "__main__":
    load_project_blueprint("FLT")
    load_project_macros("FLT")
    app.run(port=5002)
