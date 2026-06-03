# Diagnosis: missing formal source bodies in RDS `v2`

**Status:** diagnosis only — nothing fixed, mitigated, or loaded.
**Trigger:** a judged edge (`Matrix.det_mul`, sim 1.0, verdict NON-MATCH) showed an
empty `FORMAL code (Lean)` cell in the review workbook.

## TL;DR

`statement.body` (the Lean source) is empty for **182,651 / 388,105 formal nodes
(47.06%)** in RDS. **Root cause: a v3 build regression** — the ingestion ran
projects in **alphabetical order** with `INSERT OR IGNORE`, so `ClassFieldTheory`,
`FLT`, `HarderNarasimhan` (each carrying the full Mathlib dependency closure but
**no statements file**) were inserted *before* Mathlib and claimed the shared
Mathlib nodes with empty signatures; the later signature-bearing Mathlib insert
was silently skipped. **Recoverable** — 97.8% of the bodies exist in the local v2
DB, and a corrected DB already exists on klone (0.9% empty). **RDS still holds the
broken data.**

## Provenance check (it really is empty in RDS)

`statement_id 4dc52fca-…6a15231e` (`Matrix.det_mul`), live on the `v2` cluster, read-only:
- `body IS NULL` → False (empty string, not NULL); `octet_length`/`length` → 0
- `md5(body)` → `d41d8cd98f00b204e9800998ecf8427e` = md5 of the empty string
- `decl_name`, `module`, `file_path` present; `docstring` also empty.

## The two Lean exports (where the `kind` split originates)

`formalized_graph_v2/lean-graph` has two export entry points:

| export | `decl_type` source | carries |
|---|---|---|
| unified **graph** (`ImportGraph/Export/NdjsonUnified.lean`, kinds via `ImportGraph/Types.lean`) → `*.ndjson` | **abbreviated**: `.theorem=>"thm"`, `.definition=>"def"`, `.structure=>"struct"`, `.instance=>"inst"`, `.inductive=>"ind"`, `.constructor=>"ctor"` | nodes + **edges only, no signature** |
| **statements** (`MainExportStatements.lean`) → `*_statements.jsonl` | **full-word**: `"theorem"`, `"definition"`, … | `signature` + `docstring` |

Confirmed in the generated data: `add-combi.ndjson` records are
`{decl_type:"thm", edges, module, name}` (no signature);
`add-combi_statements.jsonl` records are
`{name, module, decl_type:"theorem", signature, docstring}`.

So body presence is decided entirely by which export a node came from — and the
RDS correlation is perfect: abbreviated kind ⟺ empty body (181,311/181,311);
full-word kind ⟺ has body (205,454/206,794; the 1,340 full-word empties are
`class` 1,153 + `opaque` 187 — kinds with no abbreviated twin / no slice).

## The merge bug (`ingestion/ingest_ndjson.py:110-120`)

```python
for name, info in nodes.items():        # nodes = ALL decls from the unified .ndjson graph
    stmt = stmts.get(name, {})          # left-join to statements JSONL by name
    kind = stmt.get("decl_type", info["kind"])   # full-word if present, ELSE abbreviated graph kind
    signature = stmt.get("signature", "")        # source if present, ELSE ""   ← empty body
    docstring = stmt.get("docstring", "")
```

Node set = the unified graph (every decl, incl. cross-project edge targets).
`signature`/`docstring` come **only** from the statements JSONL. A decl absent
from the statements file → abbreviated kind **and** empty body+docstring.
Insert is `INSERT OR IGNORE` on `full_name` (`corpus_v3/ingestion/database.py:117`)
→ **first writer wins**.

## Why v3 regressed (the order bug)

`corpus_v3/jobs/ingest_corpus.sbatch` runs `ingestion.ingest --all ndjson/`, which
ingests projects **alphabetically**. v3 project `id` (= insert order):

```
1 Batteries_v427 · 2 Batteries_v428 · 3 Batteries_v429 ·
4 ClassFieldTheory · 5 FLT · 6 HarderNarasimhan · 7 Mathlib_v427 · 22 Mathlib_v428 · 23 Mathlib_v429 · …
```

`ClassFieldTheory` (id 4), `FLT` (5), `HarderNarasimhan` (6) ingested **before**
`Mathlib_v427` (7). Each ships a unified `.ndjson` containing its entire Mathlib
dependency closure (ClassFieldTheory alone = 162,729 nodes) but a missing/partial
`_statements.jsonl` (90% / 93% / 79% empty). They claimed the shared Mathlib nodes
with empty signatures; `INSERT OR IGNORE` then skipped Mathlib_v427's
signature-bearing rows.

Contrast: the **v2** script `scripts/run_ingest.sh:45` explicitly *"Ingest Mathlib
first (base layer — all other projects resolve targets here)"* — which is why v2
builds have near-full coverage.

## Cross-check across the generated DBs

| DB | nodes | empty signature | first ingested |
|---|---|---|---|
| `corpus_v2_mathlib_plus_v4.29.db` | 385,504 | 0.8% | — |
| `corpus_v2_mathlib_plus_v4.27_v4.28_v4.29.db` | 404,491 | 2.6% | — |
| **`v3/corpus_v3.db`** (== RDS, to the row) | 388,105 | **47.1%** | Batteries, ClassFieldTheory, FLT, … Mathlib |
| klone `corpus_v3_fixed/corpus_v3 (corrected ingestion order).db` | 388,105 | **0.9%** | **Mathlib_v427/428/429 first** |

The corrected DB (Mathlib-first) drops empties 47.1% → 0.9% with the *same inputs*
— conclusive that ingestion order + `INSERT OR IGNORE` is the cause. The
`corpus_v3_fixed/` dir on klone also has a `remap_dryrun/`, i.e. the fix was
already attempted but **never loaded into RDS** (RDS still has the broken DB).

## Recoverability

- 178,662 / 182,651 (**97.8%**) of empty-in-v3 bodies have a real signature in
  `corpus_v2_mathlib_plus_v4.27_v4.28_v4.29.db`; only 82 absent; 3,907 empty in
  both (the legit class/opaque cases). `Matrix.det_mul` → `theorem`, signature
  length 166 in the v2 DB.
- A corrected v3 DB (0.9% empty) already exists on klone.
- So the fix is a re-ingest-in-correct-order + reload to RDS, **not** re-extraction
  from Lean repos.

## Other formal metadata tables/equivalents

`statement.body` is the only column holding Lean source anywhere in `v2` (scanned
all 29 tables / every `text` column). `formal_metadata` (decl_name, module,
file_path, docstring, is_instance) has no source; `formal_dependency` is edges;
`slogan` holds the generated NL slogans in its own table (why slogans are present
even when bodies are not). No table other than `statement.body` can carry it.

## Impact on the matching work

- 60.5% of the 8,022 judged ≥0.90 edges (4,394 matches / 456 non-matches) were
  graded with an empty formal body — the judge saw slogan + decl_name only.
- The `Matrix.det_mul` verdict is still correct (standard commutative determinant
  vs. the paper's dual-quaternion quasi-determinant), but the 60.5% empty-body rate
  is a real methodological caveat for the paper.

## Open follow-ups (not started — diagnosis only)

- Re-ingest with Mathlib-first ordering (or fix `ingest --all` to order base libs
  first / make signature-bearing inserts win), then reload RDS from the corrected DB.
- Decide whether to re-grade the affected edges once bodies are present.
- Consider a uniqueness/precedence guard so `INSERT OR IGNORE` can't let an
  empty-signature row block a populated one.
