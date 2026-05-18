#!/bin/bash
# Pipeline A: rebuild + extract 3 v4.29.0 projects (pfr, Sphere-Packing-Lean, ClassFieldTheory)
# Reuses existing v4.29.0 lean-graph binary.

set -euo pipefail
SCRIPTS="/gscratch/amath/simku22/TheoremSearch/formalized_graph_v2/scripts"

REBUILD_JOB=$(sbatch --parsable "$SCRIPTS/pipeline_a_v429_rebuild.sh")
echo "Pipeline A rebuild job: $REBUILD_JOB"

EXTRACT_JOB=$(sbatch --parsable --dependency=afterok:"$REBUILD_JOB" "$SCRIPTS/pipeline_a_v429_extract.sh")
echo "Pipeline A extract job: $EXTRACT_JOB (depends on $REBUILD_JOB)"
