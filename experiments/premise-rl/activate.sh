#!/bin/bash
source $HOME/miniconda3/etc/profile.d/conda.sh
conda activate /gscratch/amath/$USER/conda-envs/premise-rl
set -a
source /gscratch/amath/$USER/premise-rl/.env
set +a
echo "premise-rl env + secrets loaded"