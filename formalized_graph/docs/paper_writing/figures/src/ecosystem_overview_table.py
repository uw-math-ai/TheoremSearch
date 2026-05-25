"""LaTeX table accompanying the ecosystem-overview figure.

Reads the same /tmp/ecosystem_data.json the figure script consumes and
writes a booktabs table to ../out/ecosystem_overview_table.tex.

Rows: all 24 non-Mathlib projects, sorted by NL-link count desc, ties
broken by statement count desc. Top-5 by NL-link count are bolded and get
a star superscript matching the gold-ring annotation in the figure.

Columns: Project | Statements | Edges->Mathlib (%) | NL links.
"""
from __future__ import annotations
import json
from pathlib import Path

DATA_PATH = Path("/tmp/ecosystem_data.json")
OUT_PATH  = Path(__file__).resolve().parents[1] / "out" / "ecosystem_overview_table.tex"

with DATA_PATH.open() as f:
    DATA = json.load(f)

projects = list(DATA["projects"])

# Sort: NL links desc, then statements desc.
projects.sort(key=lambda p: (-p["nl_link_count"], -p["statements"]))

# Top-5 by NL link count (ties broken by stmt count via the sort above).
top5_names = {p["project"] for p in projects[:5]}

def fmt_stmts(n: int) -> str:
    return f"{n:,}"

def fmt_pct(f: float) -> str:
    return f"{100.0 * f:.1f}\\%"

def fmt_nl(p: dict) -> str:
    n = p["nl_link_count"]
    if p["project"] in top5_names:
        return f"\\textbf{{{n}}}\\textsuperscript{{\\(\\star\\)}}"
    return str(n)

def fmt_proj(p: dict) -> str:
    # Escape underscores etc. None in current set but be safe.
    name = p["project"].replace("_", "\\_")
    return f"\\texttt{{{name}}}"

rows = []
for p in projects:
    rows.append(
        f"    {fmt_proj(p):<40s} & {fmt_stmts(p['statements']):>7s} "
        f"& {fmt_pct(p['frac_mathlib_edges']):>7s} "
        f"& {fmt_nl(p):>30s} \\\\"
    )

table = (
    "\\begin{table}[h]\n"
    "  \\centering\n"
    "  \\setlength{\\tabcolsep}{4pt}\n"
    "  \\small\n"
    "  \\begin{tabular}{lrrr}\n"
    "    \\toprule\n"
    "    \\textbf{Project} & \\textbf{Statements} "
    "& \\textbf{Edges$\\to$Mathlib} & \\textbf{NL links} \\\\\n"
    "    \\midrule\n"
    + "\n".join(rows) + "\n"
    "    \\bottomrule\n"
    "  \\end{tabular}\n"
    "  \\caption{Per-project statistics for the ecosystem overview "
    "(Fig.~\\ref{fig:ecosystem-overview}).\n"
    "           Stars indicate the top-5 most NL-linked projects "
    "(gold rings in figure).\n"
    "           NL links = mutual rank-1 pairs anchored to the project; "
    "Edges$\\to$Mathlib =\n"
    "           fraction of outgoing \\texttt{formal\\_dependency} edges "
    "that target Mathlib.}\n"
    "  \\label{tab:ecosystem-overview}\n"
    "\\end{table}\n"
)

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
OUT_PATH.write_text(table)
print(f"wrote {OUT_PATH}")
print(f"  {len(projects)} rows, top-5 starred: {sorted(top5_names)}")

# Console preview of the sort for quick verification.
print()
print(f"{'project':<32s} {'stmts':>7s} {'edges%':>7s} {'nl':>4s}")
for p in projects:
    star = "*" if p["project"] in top5_names else " "
    print(f"{p['project']:<32s} {p['statements']:>7,d} "
          f"{100*p['frac_mathlib_edges']:>6.1f}% {p['nl_link_count']:>4d}{star}")
