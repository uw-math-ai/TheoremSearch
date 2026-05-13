"""Build data.json for the d3 visualizer.

Emits:
  - fl_nodes/fl_edges: the 37 apap \\lean-tagged decls + sig/def edges among them
  - bp_nodes/bp_edges: blueprint \\label nodes + \\uses edges
  - lean_to_label: map from Lean decl name to blueprint label (via \\lean{})
  - slogans: { decl: { isolated, slogan_context, code_context } }
"""
from __future__ import annotations
import json, os, re, sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DB = ROOT / "formalized_graph_v2/data/generated/corpus_v2_mathlib_plus_v4.29.db"
BP = ROOT / "formalized_graph/data/formalization_projects/apap/blueprint/src/chapter"

decls = [l.strip() for l in (HERE / "decls.txt").read_text().splitlines() if l.strip()]

# --- slogans ---
slogans: dict[str, dict] = {d: {} for d in decls}
for mode in ("isolated", "slogan_context", "code_context"):
    for line in (HERE / f"outputs/slogans_{mode}.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        slogans.setdefault(r["decl"], {})[mode] = {
            "slogan": r.get("slogan", ""),
            "confidence": r.get("confidence", ""),
        }

# --- FL graph ---
con = sqlite3.connect(str(DB)); con.row_factory = sqlite3.Row
apap_pid = con.execute("SELECT id FROM projects WHERE name='apap'").fetchone()["id"]

fl_nodes = []
name_to_id = {}
for d in decls:
    row = con.execute(
        "SELECT id, full_name, kind, signature, docstring FROM nodes "
        "WHERE project_id=? AND (full_name=? OR full_name LIKE ?)",
        (apap_pid, d, f"%.{d}"),
    ).fetchone()
    if not row:
        row = con.execute(
            "SELECT id, full_name, kind, signature, docstring FROM nodes "
            "WHERE full_name=? OR full_name LIKE ?", (d, f"%.{d}"),
        ).fetchone()
    if row:
        name_to_id[d] = row["id"]
        fl_nodes.append({
            "id": d,
            "full_name": row["full_name"],
            "kind": row["kind"],
            "signature": (row["signature"] or "")[:600],
            "docstring": (row["docstring"] or "")[:400],
            "resolved": True,
        })
    else:
        fl_nodes.append({"id": d, "full_name": d, "kind": "unresolved",
                          "signature": "", "docstring": "", "resolved": False})

id_to_name = {v: k for k, v in name_to_id.items()}
fl_edges = []
if name_to_id:
    qmarks = ",".join("?" * len(name_to_id))
    rows = con.execute(
        f"SELECT source_id, target_id, edge_type FROM edges "
        f"WHERE source_id IN ({qmarks}) AND target_id IN ({qmarks}) "
        f"AND edge_type IN ('sig','def')",
        list(name_to_id.values()) * 2,
    ).fetchall()
    for r in rows:
        fl_edges.append({
            "source": id_to_name[r["source_id"]],
            "target": id_to_name[r["target_id"]],
            "type": r["edge_type"],
        })

# --- Blueprint graph ---
LABEL_RE = re.compile(r"\\label\{([^}]+)\}")
LEAN_RE = re.compile(r"\\lean\{([^}]+)\}")
USES_RE = re.compile(r"\\uses\{([^}]*)\}")
ENV_RE = re.compile(
    r"\\begin\{(theorem|lemma|definition|proposition|corollary)\}"
    r"(.*?)\\end\{\1\}",
    re.DOTALL,
)

bp_nodes_by_label: dict[str, dict] = {}
bp_edges = []
lean_to_label: dict[str, str] = {}

for tex in sorted(BP.glob("*.tex")):
    text = tex.read_text()
    for m in ENV_RE.finditer(text):
        kind, body = m.group(1), m.group(2)
        labels = LABEL_RE.findall(body)
        leans = []
        for lm in LEAN_RE.findall(body):
            for n in lm.split(","):
                n = n.strip()
                if n:
                    leans.append(n)
        uses = []
        for um in USES_RE.findall(body):
            for u in um.split(","):
                u = u.strip()
                if u:
                    uses.append(u)
        if not labels:
            continue
        label = labels[0]
        # strip leading whitespace and \leanok markers from body
        clean = re.sub(r"\\leanok|\\proves\{[^}]*\}|\\lean\{[^}]*\}|\\label\{[^}]*\}|\\uses\{[^}]*\}", "", body).strip()
        clean = re.sub(r"\n{3,}", "\n\n", clean)[:1200]
        bp_nodes_by_label[label] = {
            "id": label, "kind": kind, "leans": leans, "body": clean,
            "chapter": tex.stem,
        }
        for u in uses:
            bp_edges.append({"source": label, "target": u})
        for ln in leans:
            lean_to_label[ln] = label

# drop edges pointing to unknown labels
known = set(bp_nodes_by_label)
bp_edges = [e for e in bp_edges if e["target"] in known and e["source"] in known]

# --- LaTeX macros from blueprint preamble ---
# KaTeX wants a flat {name: expansion} map. We grab \newcommand and
# \DeclareMathOperator forms. \newcommand{\foo}[n]{body} -> "\foo": "body"
# (with #1, #2 placeholders preserved — KaTeX supports them).
macros: dict[str, str] = {}

def _read_braced(text: str, i: int) -> tuple[str, int] | None:
    """If text[i] == '{', return (content, index_after_close); else None."""
    if i >= len(text) or text[i] != "{":
        return None
    depth, j = 0, i
    while j < len(text):
        c = text[j]
        if c == "\\" and j + 1 < len(text):
            j += 2; continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[i+1:j], j + 1
        j += 1
    return None

def _extract_macros(text: str) -> None:
    for m in re.finditer(r"\\(?:re|provide)?newcommand\*?|\\providecommand\*?", text):
        i = m.end()
        # optional whitespace, then {\name}
        while i < len(text) and text[i] in " \t":
            i += 1
        name_block = _read_braced(text, i)
        if not name_block:
            continue
        name_inner, i = name_block
        name_inner = name_inner.strip()
        if not re.fullmatch(r"\\[A-Za-z]+\*?", name_inner):
            continue
        # optional [n] arity and [default]
        while i < len(text) and text[i] == "[":
            j = text.find("]", i)
            if j < 0: break
            i = j + 1
        body = _read_braced(text, i)
        if not body:
            continue
        if name_inner in ("\\lean","\\leanok","\\proves","\\uses","\\label"):
            continue
        macros[name_inner] = body[0]
    for m in re.finditer(r"\\DeclareMathOperator\*?", text):
        i = m.end()
        nb = _read_braced(text, i)
        if not nb: continue
        name, i = nb
        bb = _read_braced(text, i)
        if not bb: continue
        macros[name.strip()] = f"\\operatorname{{{bb[0].strip()}}}"

preamble_dir = BP.parent / "preamble"
for tex in sorted(preamble_dir.glob("*.tex")) if preamble_dir.exists() else []:
    _extract_macros(tex.read_text())

# KaTeX-unfriendly overrides: \E in apap uses \mathchoice/\vcenter which KaTeX
# doesn't support. Replace with a plain \mathbb{E}.
macros["\\E"] = "\\mathbb{E}"

data = {
    "fl_nodes": fl_nodes,
    "fl_edges": fl_edges,
    "bp_nodes": list(bp_nodes_by_label.values()),
    "bp_edges": bp_edges,
    "lean_to_label": lean_to_label,
    "slogans": slogans,
    "katex_macros": macros,
}
out = HERE / "data.json"
out.write_text(json.dumps(data, ensure_ascii=False, indent=2))
print(f"FL: {len(fl_nodes)} nodes, {len(fl_edges)} edges  ({sum(1 for n in fl_nodes if n['resolved'])} resolved)")
print(f"BP: {len(bp_nodes_by_label)} nodes, {len(bp_edges)} edges")
print(f"lean_to_label: {len(lean_to_label)} mappings")
print(f"KaTeX macros: {len(macros)}")
print(f"-> {out}")
