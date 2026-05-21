#!/bin/bash
#SBATCH --job-name=lg-gibbs-measure
#SBATCH --account=amath-ckpt
#SBATCH --partition=ckpt-all
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --requeue
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=aurasoph@uw.edu
#SBATCH --output=/gscratch/amath/aurasoph/lean-graph-corpus-v3/logs/proj-%x-%j.out
#SBATCH --error=/gscratch/amath/aurasoph/lean-graph-corpus-v3/logs/proj-%x-%j.err

# Build gibbs-measure + leanGraph dep, extract NDJSON + JSONL.

set -euo pipefail

PROJECT=gibbs-measure
REPO=YaelDillies/gibbs-measure
REF=HEAD
TC=leanprover/lean4:v4.29.0
LG_BRANCH=lean-v4.29
MAIN_LIB=GibbsMeasure

OUT=/gscratch/amath/aurasoph/lean-graph-corpus-v3/ndjson
SIF=/gscratch/scrubbed/aurasoph/lean-check.sif
ELAN_HOST=/gscratch/scrubbed/aurasoph/.elan
WS=/tmp/lg-proj-${SLURM_JOB_ID}/$PROJECT

mkdir -p "$OUT" "$ELAN_HOST" "$(dirname "$WS")"
echo "[$(date +%T)] host=$(hostname) PROJECT=$PROJECT REF=$REF TC=$TC MAIN_LIB=$MAIN_LIB"

# Clone
case "$REF" in
    HEAD)  git clone "https://github.com/$REPO" "$WS" ;;
    tag:*) git clone --branch "${REF#tag:}" "https://github.com/$REPO" "$WS" ;;
    sha:*) git clone "https://github.com/$REPO" "$WS" && (cd "$WS" && git checkout -q "${REF#sha:}") ;;
    *)     echo "bad REF: $REF"; exit 2 ;;
esac
cd "$WS"

# Add leanGraph require (handle both .lean and .toml lakefiles)
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
    echo "no lakefile"; exit 3
fi

# Inner script (runs inside apptainer)
INNER=/tmp/lg-proj-${SLURM_JOB_ID}/inner.sh
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

echo "[$(ts)] lake build $MAIN_LIB graph export_statements"
lake build "$MAIN_LIB" graph export_statements

echo "[$(ts)] extract NDJSON"
# `lake exe graph` may exit non-zero after writing .ndjson — its post-write
# fallback tries to graphviz a non-existent .dot file. The NDJSON itself is
# fully written before that point. Check the file, not the exit code.
lake exe graph --mode unified --to "$MAIN_LIB" "/out/$PROJECT.ndjson" || true
if [ ! -s "/out/$PROJECT.ndjson" ]; then
    echo "FAIL: /out/$PROJECT.ndjson missing or empty" >&2
    exit 4
fi

echo "[$(ts)] extract JSONL"
lake exe export_statements --to "$MAIN_LIB" --output "/out/${PROJECT}_statements.jsonl"
if [ ! -s "/out/${PROJECT}_statements.jsonl" ]; then
    echo "FAIL: /out/${PROJECT}_statements.jsonl missing or empty" >&2
    exit 5
fi

echo "[$(ts)] outputs:"
wc -l "/out/$PROJECT.ndjson" "/out/${PROJECT}_statements.jsonl"
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
    --env "PROJECT=$PROJECT" \
    --env "MAIN_LIB=$MAIN_LIB" \
    --pwd /work "$SIF" bash /inner.sh

echo "[$(date +%T)] === DONE $PROJECT ==="
