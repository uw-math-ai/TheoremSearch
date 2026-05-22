"""Look for any blueprint-label hints in the corpus_v2 SQLite DB."""

import sqlite3
import re
from pathlib import Path

DB = Path("/home/ericleonen/TheoremSearch/corpus_v2_mathlib_plus_v4.27_v4.28_v4.29.db")
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

# 1. Anywhere "blueprint" shows up in docstrings, by project.
print("== docstrings containing 'blueprint' ==")
rows = conn.execute("""
    SELECT p.name AS proj, COUNT(*) AS n
      FROM nodes n JOIN projects p ON p.id = n.project_id
     WHERE n.docstring LIKE '%blueprint%' COLLATE NOCASE
     GROUP BY p.name ORDER BY n DESC
""").fetchall()
for r in rows:
    print(f"  {r['proj']:35s} {r['n']:>6,}")
if not rows:
    print("  (none)")

# 2. Same for signatures (sometimes attributes leak in).
print("\n== signatures containing 'blueprint' ==")
rows = conn.execute("""
    SELECT p.name AS proj, COUNT(*) AS n
      FROM nodes n JOIN projects p ON p.id = n.project_id
     WHERE n.signature LIKE '%blueprint%' COLLATE NOCASE
     GROUP BY p.name ORDER BY n DESC
""").fetchall()
for r in rows:
    print(f"  {r['proj']:35s} {r['n']:>6,}")
if not rows:
    print("  (none)")

# 3. Show a handful of example docstring snippets that mention blueprint.
print("\n== example docstrings (up to 10) ==")
rows = conn.execute("""
    SELECT p.name AS proj, n.full_name, n.docstring
      FROM nodes n JOIN projects p ON p.id = n.project_id
     WHERE n.docstring LIKE '%blueprint%' COLLATE NOCASE
     LIMIT 10
""").fetchall()
for r in rows:
    ds = (r["docstring"] or "").replace("\n", " ")
    if len(ds) > 200:
        ds = ds[:200] + "..."
    print(f"  [{r['proj']}] {r['full_name']}")
    print(f"    {ds}\n")

# 4. Try common blueprint-label patterns. A few I've seen in the wild:
#    - "Label: X.Y.Z"
#    - "blueprint label: X.Y.Z"
#    - "@[blueprint X.Y.Z]"
#    - "%%[blueprint X.Y.Z]"
#    - "\lean{X}" referenced from LaTeX side; reverse direction "\\label{..}"
patterns = [
    r"@\[blueprint\b",
    r"blueprint\s*label",
    r"\\label\{",
    r"\\lean\{",
    r"\bLABEL\s*:",
]
print("== signature+docstring matches by pattern ==")
for pat in patterns:
    rx = re.compile(pat, re.IGNORECASE)
    hits = 0
    sample = None
    for n in conn.execute("SELECT full_name, signature, docstring FROM nodes"):
        blob = (n["signature"] or "") + "\n" + (n["docstring"] or "")
        if rx.search(blob):
            hits += 1
            if sample is None:
                sample = (n["full_name"], blob[max(0, rx.search(blob).start() - 30):rx.search(blob).end() + 60])
    print(f"  /{pat}/ → {hits:,} hits")
    if sample:
        name, snippet = sample
        print(f"    e.g. {name}: ...{snippet.strip()}...")

conn.close()
