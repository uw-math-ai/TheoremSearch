"""Follow-up inspection: distinct enum-like values + the full project list."""

import sqlite3
from pathlib import Path

DB = Path("/home/ericleonen/TheoremSearch/corpus_v2_mathlib_plus_v4.27_v4.28_v4.29.db")
uri = f"file:{DB}?mode=ro"
conn = sqlite3.connect(uri, uri=True)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("== edge_type distribution ==")
for r in cur.execute("SELECT edge_type, COUNT(*) AS n FROM edges GROUP BY edge_type ORDER BY n DESC"):
    print(f"  {r['edge_type']:20s} {r['n']:>12,}")

print("\n== node kind distribution ==")
for r in cur.execute("SELECT kind, COUNT(*) AS n FROM nodes GROUP BY kind ORDER BY n DESC"):
    print(f"  {r['kind']:20s} {r['n']:>12,}")

print("\n== nodes per project ==")
for r in cur.execute("""
    SELECT p.id, p.name, COUNT(n.id) AS n_nodes
      FROM projects p LEFT JOIN nodes n ON n.project_id = p.id
     GROUP BY p.id, p.name
     ORDER BY n_nodes DESC
"""):
    print(f"  [{r['id']:>3}] {r['name']:30s} {r['n_nodes']:>10,}")

print("\n== full project list ==")
for r in cur.execute("SELECT * FROM projects ORDER BY id"):
    print(dict(r))

conn.close()
