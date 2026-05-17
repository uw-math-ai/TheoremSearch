#!/bin/bash
# Pipeline B: v4.28.0 — sphere-eversion + PrimeNumberTheoremAnd
# Builds Mathlib + lean-graph @ lean-v4.28 then rebuilds + extracts both projects.
# Prereq: elan toolchain v4.28.0 installed (`elan toolchain install leanprover/lean4:v4.28.0`).

set -euo pipefail
SCRIPTS="/gscratch/amath/simku22/TheoremSearch/formalized_graph_v2/scripts"

BUILD_JOB=$(sbatch --parsable "$SCRIPTS/pipeline_b_v428_build.sh")
echo "Pipeline B build job: $BUILD_JOB"

REBUILD_JOB=$(sbatch --parsable --dependency=afterok:"$BUILD_JOB" "$SCRIPTS/pipeline_b_v428_rebuild.sh")
echo "Pipeline B rebuild job: $REBUILD_JOB (depends on $BUILD_JOB)"

EXTRACT_JOB=$(sbatch --parsable --dependency=afterany:"$REBUILD_JOB" "$SCRIPTS/pipeline_b_v428_extract.sh")
echo "Pipeline B extract job: $EXTRACT_JOB (depends on $REBUILD_JOB)"
