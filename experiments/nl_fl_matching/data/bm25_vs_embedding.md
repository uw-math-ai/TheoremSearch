# BM25 baseline vs qwen3-8b embedding

Bootstrap 95% CIs over 2000 resamples. Gold definition (1,595 blueprint pairs) is embedding-independent; both retrievers evaluated against the same gold set.

| sweep | n | Hit@1 | Hit@5 | Hit@10 | MRR@10 |
|---|---:|---:|---:|---:|---:|
| qwen3-8b — f→i (vs 11.7M) | 1562 | 42.6% [40.2, 45.1] | 64.3% [61.9, 66.6] | 69.8% [67.6, 72.2] | 51.8% [49.6, 53.9] |
| bm25 — f→i (vs 2,544 blueprint) | 1577 | 43.5% [41.0, 45.8] | 72.4% [70.1, 74.6] | 79.8% [77.7, 81.8] | 55.7% [53.7, 57.7] |
| qwen3-8b — i→f (vs 36,708 projformal) | 1308 | 42.6% [39.8, 45.3] | 67.0% [64.4, 69.5] | 71.7% [69.2, 74.2] | 53.1% [50.8, 55.5] |
| bm25 — i→f (vs 36,708 projformal) | 1308 | 31.3% [28.9, 33.9] | 53.7% [51.0, 56.4] | 61.0% [58.4, 63.7] | 41.0% [38.7, 43.4] |
