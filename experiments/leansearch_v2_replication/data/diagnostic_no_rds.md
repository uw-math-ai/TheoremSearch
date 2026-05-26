# MathlibQR diagnostic — n=946 cells

## Headline

- full-946:  n=946  recall@10=0.553  nDCG@10=0.365  top1=0.198
- fair-810:  n=810  recall@10=0.568  nDCG@10=0.370  top1=0.194

### vs LSv2 (fair-810, from arXiv:2605.13137 Table 1)

| system | nDCG@10 | Recall@10 |
|---|---:|---:|
| LSv2 rerank (Qwen3-Reranker-8B) | **0.623** | **0.780** |
| LSv2 retriever-only             | 0.494     | 0.657     |
| LeanFinder (reported)           | 0.533 | 0.698 |
| LeanExplore (reported)          | 0.393 | 0.569 |
| **Ours (Lean Repo retriever)**  | **0.370** | **0.568** |

Gap vs LSv2 retriever-only: ΔnDCG@10 = -0.124, ΔRecall@10 = -0.089

## Breakdown (fair-810)

### by style

| style | n | recall@10 | nDCG@10 | top1 |
|---|---|---|---|---|
| q1a_lean | 170 | 0.494 | 0.337 | 0.194 |
| q1b_latex | 171 | 0.567 | 0.372 | 0.216 |
| q1c_natural | 170 | 0.624 | 0.415 | 0.229 |
| q2_slogan | 168 | 0.571 | 0.351 | 0.161 |
| q3_nickname | 108 | 0.602 | 0.382 | 0.167 |
| q4_special_case | 23 | 0.522 | 0.328 | 0.130 |

### by kind

| kind | n | recall@10 | nDCG@10 | top1 |
|---|---|---|---|---|
| class | 134 | 0.410 | 0.239 | 0.075 |
| def | 105 | 0.495 | 0.288 | 0.124 |
| inductive | 25 | 0.520 | 0.353 | 0.240 |
| instance | 97 | 0.732 | 0.549 | 0.371 |
| lemma | 5 | 0.800 | 0.612 | 0.400 |
| structure | 153 | 0.379 | 0.213 | 0.092 |
| theorem | 291 | 0.711 | 0.478 | 0.261 |

### by difficulty

| difficulty | n | recall@10 | nDCG@10 | top1 |
|---|---|---|---|---|
| Easy | 439 | 0.601 | 0.405 | 0.223 |
| Hard | 371 | 0.528 | 0.328 | 0.159 |

## Hit-rank distribution (fair-810)

| rank | count | cumulative recall |
|---|---:|---:|
| 1 | 157 | 0.194 |
| 2 | 95 | 0.311 |
| 3 | 49 | 0.372 |
| 4 | 42 | 0.423 |
| 5 | 33 | 0.464 |
| 6 | 24 | 0.494 |
| 7 | 14 | 0.511 |
| 8 | 15 | 0.530 |
| 9 | 11 | 0.543 |
| 10 | 20 | 0.568 |
| miss | 350 | — |

## Corpus coverage

MathlibQR decls present in our v427/v428 formal_metadata: **192/200** (missing 8).

Missing decls (each contributes a hard 0 to recall across all populated styles):
  - `CategoryTheory.FundamentalGroupoid`
  - `GCDMonoid.gcd_mul_lcm`
  - `InformationTheory.UniquelyDecodable`
  - `InformationTheory.kraft_mcmillan_inequality`
  - `Nat.RecursiveIn`
  - `ProbabilityTheory.PMF.instFunLike`
  - `Representation.IntertwiningMap.instLinearMapClass`
  - `SimplicialObject.Augmented.ExtraDegeneracy`

