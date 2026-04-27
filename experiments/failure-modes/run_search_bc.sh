#!/bin/zsh
cd /Users/vasil/Github/TheoremSearch/experiments/failure-modes
cat data/queries_b.jsonl data/queries_c.jsonl > data/queries_bc.jsonl
python3 -c "
import sys
sys.path.insert(0, '.')
import run_search
run_search.QUERIES = run_search.ROOT / 'data' / 'queries_bc.jsonl'
run_search.OUT = run_search.ROOT / 'results' / 'raw_bc.jsonl'
run_search.WORKERS = 8
run_search.main()
" 2>&1
