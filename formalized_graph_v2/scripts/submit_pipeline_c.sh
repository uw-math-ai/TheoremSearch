#!/bin/bash
# Pipeline C: v4.27.0 — formal-conjectures
# Builds Mathlib + lean-graph @ lean-v4.27 then rebuilds + extracts.
# Prereq: elan toolchain v4.27.0 installed (`elan toolchain install leanprover/lean4:v4.27.0`).

set -euo pipefail
SCRIPTS="/gscratch/amath/simku22/TheoremSearch/formalized_graph_v2/scripts"

BUILD_JOB=$(sbatch --parsable "$SCRIPTS/pipeline_c_v427_build.sh")
echo "Pipeline C build job: $BUILD_JOB"

REBUILD_JOB=$(sbatch --parsable --dependency=afterok:"$BUILD_JOB" "$SCRIPTS/pipeline_c_v427_rebuild.sh")
echo "Pipeline C rebuild job: $REBUILD_JOB (depends on $BUILD_JOB)"

EXTRACT_JOB=$(sbatch --parsable --dependency=afterok:"$REBUILD_JOB" "$SCRIPTS/pipeline_c_v427_extract.sh")
echo "Pipeline C extract job: $EXTRACT_JOB (depends on $REBUILD_JOB)"
