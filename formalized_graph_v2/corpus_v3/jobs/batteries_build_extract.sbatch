#!/bin/bash
#SBATCH --job-name=batteries-build-extract
#SBATCH --account=amath-ckpt
#SBATCH --partition=ckpt-all
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --time=01:30:00
#SBATCH --requeue
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=aurasoph@uw.edu
#SBATCH --output=/gscratch/amath/aurasoph/lean-graph-corpus-v3/logs/%x-%j.out
#SBATCH --error=/gscratch/amath/aurasoph/lean-graph-corpus-v3/logs/%x-%j.err

# Build + extract Batteries at a specific Lean version.
# Required env:
#   BATTERIES_TAG  - e.g. "v4.28.0"
#   TC             - toolchain, e.g. "leanprover/lean4:v4.28.0"
#   LG_BRANCH      - lean-graph branch, e.g. "lean-v4.28"
#   VLABEL         - filename label, e.g. "v428"
set -euo pipefail
: "${BATTERIES_TAG:?}" ; : "${TC:?}" ; : "${LG_BRANCH:?}" ; : "${VLABEL:?}"

OUT=/gscratch/amath/aurasoph/lean-graph-corpus-v3/ndjson
SIF=/gscratch/scrubbed/aurasoph/lean-check.sif
ELAN_HOST=/gscratch/scrubbed/aurasoph/.elan
WS=/tmp/batteries-${VLABEL}-${SLURM_JOB_ID}

mkdir -p "$OUT" "$ELAN_HOST"
echo "[$(date +%T)] host=$(hostname) BATTERIES_TAG=$BATTERIES_TAG TC=$TC LG=$LG_BRANCH VLABEL=$VLABEL"

echo "[$(date +%T)] === git clone batteries @ $BATTERIES_TAG ==="
git clone --depth 1 --branch "$BATTERIES_TAG" https://github.com/leanprover-community/batteries "$WS"
cd "$WS"

# Add leanGraph as a require. Batteries uses lakefile.lean.
echo "[$(date +%T)] === append leanGraph require ==="
if [ -f lakefile.lean ]; then
    cat >> lakefile.lean <<EOF

require leanGraph from git "https://github.com/aurasoph/lean-graph" @ "$LG_BRANCH"
EOF
elif [ -f lakefile.toml ]; then
    cat >> lakefile.toml <<EOF

[[require]]
name = "leanGraph"
git = "https://github.com/aurasoph/lean-graph"
rev = "$LG_BRANCH"
EOF
else
    echo "no lakefile in batteries checkout"; exit 3
fi

INNER=/tmp/batteries_${VLABEL}_inner_${SLURM_JOB_ID}.sh
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

echo "[$(ts)] lake build Batteries graph export_statements"
lake build Batteries graph export_statements

echo "[$(ts)] extract NDJSON"
lake exe graph --mode unified --to Batteries "/out/Batteries_${VLABEL}.ndjson" || true
if [ ! -s "/out/Batteries_${VLABEL}.ndjson" ]; then
    echo "FAIL: /out/Batteries_${VLABEL}.ndjson missing or empty" >&2
    exit 4
fi

echo "[$(ts)] extract JSONL"
lake exe export_statements --to Batteries --output "/out/Batteries_${VLABEL}_statements.jsonl"
if [ ! -s "/out/Batteries_${VLABEL}_statements.jsonl" ]; then
    echo "FAIL: /out/Batteries_${VLABEL}_statements.jsonl missing or empty" >&2
    exit 5
fi

echo "[$(ts)] outputs:"
wc -l "/out/Batteries_${VLABEL}.ndjson" "/out/Batteries_${VLABEL}_statements.jsonl"
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
    --env "BATTERIES_TAG=$BATTERIES_TAG" \
    --pwd /work "$SIF" bash /inner.sh

echo "[$(date +%T)] === DONE Batteries $BATTERIES_TAG ==="
