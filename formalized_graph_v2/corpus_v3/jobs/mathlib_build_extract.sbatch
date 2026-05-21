#!/bin/bash
#SBATCH --job-name=mathlib-build-extract
#SBATCH --account=amath-ckpt
#SBATCH --partition=ckpt-all
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=03:00:00
#SBATCH --requeue
#SBATCH --output=/gscratch/amath/aurasoph/lean-graph-corpus-v3/logs/%x-%j.out
#SBATCH --error=/gscratch/amath/aurasoph/lean-graph-corpus-v3/logs/%x-%j.err

# Combined Mathlib build + extract for a specific Lean version.
# Required env (--export):
#   MATHLIB_TAG  - e.g. "v4.28.0"
#   TC           - toolchain, e.g. "leanprover/lean4:v4.28.0"
#   LG_BRANCH    - lean-graph branch, e.g. "lean-v4.28"
#   VLABEL       - short label for output filename, e.g. "v428"
set -euo pipefail
: "${MATHLIB_TAG:?}" ; : "${TC:?}" ; : "${LG_BRANCH:?}" ; : "${VLABEL:?}"

OUT=/gscratch/amath/aurasoph/lean-graph-corpus-v3/ndjson
SIF=/gscratch/scrubbed/aurasoph/lean-check.sif
ELAN_HOST=/gscratch/scrubbed/aurasoph/.elan

# Workspace on node-local SSD (clean up on teardown — Mathlib at older
# versions isn't worth persisting at GPFS).
WS=/tmp/mathlib-${VLABEL}-${SLURM_JOB_ID}

mkdir -p "$OUT" "$ELAN_HOST"
echo "[$(date +%T)] host=$(hostname) MATHLIB_TAG=$MATHLIB_TAG TC=$TC LG=$LG_BRANCH VLABEL=$VLABEL"

# Clone Mathlib at the requested tag
echo "[$(date +%T)] === git clone mathlib4 @ $MATHLIB_TAG ==="
git clone --depth 1 --branch "$MATHLIB_TAG" https://github.com/leanprover-community/mathlib4 "$WS"
cd "$WS"

# Add our leanGraph require
echo "[$(date +%T)] === append leanGraph require ==="
cat >> lakefile.lean <<EOF

require leanGraph from git "https://github.com/aurasoph/lean-graph" @ "$LG_BRANCH"
EOF

# Inner script
INNER=/tmp/mathlib_${VLABEL}_inner_${SLURM_JOB_ID}.sh
cat > "$INNER" <<'INNEREOF'
#!/bin/bash
set -e
ts() { date +%T; }
export ELAN_HOME=/elan
export PATH=/elan/bin:$PATH
export LC_ALL=C.UTF-8 LANG=C.UTF-8

[ -x /elan/bin/elan ] || curl -sSf https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh | bash -s -- -y --no-modify-path --default-toolchain none
elan toolchain list | grep -qx "$TC" || elan toolchain install "$TC"

cd /work
echo "[$(ts)] lake update leanGraph"
lake update leanGraph

echo "[$(ts)] lake build Mathlib graph export_statements (from source — no Azure cache for $MATHLIB_TAG)"
lake build Mathlib graph export_statements

echo "[$(ts)] extract NDJSON"
lake exe graph --mode unified --to Mathlib "/out/Mathlib_${VLABEL}.ndjson" || true
if [ ! -s "/out/Mathlib_${VLABEL}.ndjson" ]; then
    echo "FAIL: /out/Mathlib_${VLABEL}.ndjson missing or empty" >&2
    exit 4
fi

echo "[$(ts)] extract JSONL"
lake exe export_statements --to Mathlib --output "/out/Mathlib_${VLABEL}_statements.jsonl"
if [ ! -s "/out/Mathlib_${VLABEL}_statements.jsonl" ]; then
    echo "FAIL: /out/Mathlib_${VLABEL}_statements.jsonl missing or empty" >&2
    exit 5
fi

echo "[$(ts)] outputs:"
wc -l "/out/Mathlib_${VLABEL}.ndjson" "/out/Mathlib_${VLABEL}_statements.jsonl"
INNEREOF
chmod +x "$INNER"

echo "[$(date +%T)] === apptainer ==="
command -v apptainer >/dev/null 2>&1 || module load apptainer >/dev/null 2>&1
apptainer exec --cleanenv \
    --bind "$WS:/work" \
    --bind "$OUT:/out" \
    --bind "$ELAN_HOST:/elan" \
    --bind "$INNER:/inner.sh:ro" \
    --env "TC=$TC" \
    --env "VLABEL=$VLABEL" \
    --env "MATHLIB_TAG=$MATHLIB_TAG" \
    --pwd /work "$SIF" bash /inner.sh

echo "[$(date +%T)] === DONE Mathlib $MATHLIB_TAG ==="
