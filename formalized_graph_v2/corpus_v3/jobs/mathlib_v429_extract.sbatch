#!/bin/bash
#SBATCH --job-name=mathlib-v429-extract
#SBATCH --account=amath-ckpt
#SBATCH --partition=ckpt-all
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=02:00:00
#SBATCH --requeue
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=aurasoph@uw.edu
#SBATCH --output=/gscratch/amath/aurasoph/lean-graph-corpus-v3/logs/%x-%j.out
#SBATCH --error=/gscratch/amath/aurasoph/lean-graph-corpus-v3/logs/%x-%j.err

# Extract the Mathlib v4.29 graph (NDJSON) + statement-level JSONL.
# Uses the existing build state from .lake/build-final/ (persisted by the
# resume job). SSD-stages the oleans for fast extraction reads.
set -euo pipefail

WS=/gscratch/scrubbed/aurasoph/lean-graph-mathlib-v429-fresh
SIF=/gscratch/scrubbed/aurasoph/lean-check.sif
ELAN_HOST=/gscratch/scrubbed/aurasoph/.elan
PERSISTED_BUILD=$WS/.lake/build-final
LOCAL_BUILD=/tmp/lake-build-${SLURM_JOB_ID}
OUT=/gscratch/amath/aurasoph/lean-graph-corpus-v3/ndjson

[ -d "$WS" ] || { echo "FATAL: $WS missing"; exit 2; }
[ -d "$PERSISTED_BUILD" ] || { echo "FATAL: $PERSISTED_BUILD missing"; exit 3; }

mkdir -p "$LOCAL_BUILD" "$OUT"

echo "[$(date +%T)] host=$(hostname) cpus=$SLURM_CPUS_PER_TASK"
echo "[$(date +%T)] === Seeding LOCAL_BUILD from $PERSISTED_BUILD ==="
rsync -a "$PERSISTED_BUILD/" "$LOCAL_BUILD/"
echo "  $(find "$LOCAL_BUILD" -name '*.olean' | wc -l) oleans seeded"

# Point Mathlib's .lake/build at SSD
mkdir -p "$WS/.lake"
rm -rf "$WS/.lake/build"
ln -sfn "$LOCAL_BUILD" "$WS/.lake/build"

cd "$WS"

INNER=/tmp/mathlib_v429_extract_inner_${SLURM_JOB_ID}.sh
cat > "$INNER" <<'INNEREOF'
#!/bin/bash
set -e
ts() { date +%T; }
export ELAN_HOME=/elan
export PATH=/elan/bin:$PATH
export LC_ALL=C.UTF-8 LANG=C.UTF-8

[ -x /elan/bin/elan ] || curl -sSf https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh | bash -s -- -y --no-modify-path --default-toolchain none
elan toolchain list | grep -qx 'leanprover/lean4:v4.29.0' || elan toolchain install leanprover/lean4:v4.29.0

cd /work
echo "[$(ts)] lake update leanGraph (refresh to lean-v4.29 head)"
lake update leanGraph

echo "[$(ts)] lake build graph export_statements (binaries only — Mathlib already built)"
lake build graph export_statements

echo "[$(ts)] extract NDJSON (lake exe graph)"
# Same tolerance pattern as build_project.sbatch — the graph binary's
# post-write graphviz fallback exits non-zero on .ndjson even when the
# file was fully written. Check the file, not the exit code.
lake exe graph --mode unified --to Mathlib /out/Mathlib_v429.ndjson || true
if [ ! -s "/out/Mathlib_v429.ndjson" ]; then
    echo "FAIL: /out/Mathlib_v429.ndjson missing or empty" >&2
    exit 4
fi

echo "[$(ts)] extract JSONL (lake exe export_statements)"
lake exe export_statements --to Mathlib --output /out/Mathlib_v429_statements.jsonl
if [ ! -s "/out/Mathlib_v429_statements.jsonl" ]; then
    echo "FAIL: /out/Mathlib_v429_statements.jsonl missing or empty" >&2
    exit 5
fi

echo "[$(ts)] outputs:"
wc -l /out/Mathlib_v429.ndjson /out/Mathlib_v429_statements.jsonl
INNEREOF
chmod +x "$INNER"

echo "[$(date +%T)] === apptainer ==="
command -v apptainer >/dev/null 2>&1 || module load apptainer >/dev/null 2>&1
apptainer exec --cleanenv \
    --bind "$WS:/work" \
    --bind "$OUT:/out" \
    --bind "$ELAN_HOST:/elan" \
    --bind "$INNER:/inner.sh:ro" \
    --bind "$LOCAL_BUILD:$LOCAL_BUILD" \
    --pwd /work "$SIF" bash /inner.sh

echo "[$(date +%T)] === DONE ==="
