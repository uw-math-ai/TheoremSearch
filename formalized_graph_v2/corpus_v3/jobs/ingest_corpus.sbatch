#!/bin/bash
#SBATCH --job-name=corpus-ingest
#SBATCH --account=amath-ckpt
#SBATCH --partition=ckpt-all
#SBATCH --cpus-per-task=2
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --requeue
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=aurasoph@uw.edu
#SBATCH --output=/gscratch/amath/aurasoph/lean-graph-corpus-v3/logs/%x-%j.out
#SBATCH --error=/gscratch/amath/aurasoph/lean-graph-corpus-v3/logs/%x-%j.err

set -euo pipefail
cd /gscratch/amath/aurasoph/lean-graph-corpus-v3

echo "[$(date +%T)] === starting ingestion ==="
python3.12 -m ingestion.ingest --all ndjson/ --db corpus_v3.db
echo "[$(date +%T)] === ingestion complete — summarising ==="

python3.12 - <<'PYEOF'
import sqlite3
conn = sqlite3.connect('corpus_v3.db')
c = conn.cursor()
print('=== per-project ===')
for row in c.execute('''
    SELECT name, lean_toolchain,
           (SELECT COUNT(*) FROM nodes WHERE project_id = projects.id) AS nodes
    FROM projects ORDER BY name'''):
    print(f'  {row[0]:<32} toolchain={row[1] or "-":<10} nodes={row[2]}')
print()
print('=== totals ===')
print(f'  projects: {c.execute("SELECT COUNT(*) FROM projects").fetchone()[0]}')
print(f'  nodes:    {c.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]:,}')
print(f'  edges:    {c.execute("SELECT COUNT(*) FROM edges").fetchone()[0]:,}')
print('  edge types:')
for row in c.execute('SELECT edge_type, COUNT(*) FROM edges GROUP BY edge_type ORDER BY 2 DESC'):
    print(f'    {row[0]:<10} {row[1]:,}')
import os
print(f'\n  db size: {os.path.getsize("corpus_v3.db") / 1e9:.2f} GB')
PYEOF
echo "[$(date +%T)] === done ==="
