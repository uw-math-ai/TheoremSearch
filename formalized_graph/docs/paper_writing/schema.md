# RDS Schema (database `v2`, schema `public`)

Reference for paper writing. Tables documented in the order data flows:
**papers → statements → metadata → slogans → embeddings**, with edge
tables alongside the metadata they annotate.

Connection: `theorem-search.cluster-cx0ei6kq0qcn.us-west-2.rds.amazonaws.com:5432`,
db `v2`, user `postgres` (credentials in `.env` via Secrets Manager).

## `paper`  (1,841,292 rows)

Source-paper registry. One row per paper/repo/blueprint, regardless of source. `kind` distinguishes paper-style records. `external_id` is the natural key on its source (arxiv id, repo slug, etc).

| column | type | null |
|---|---|---|
| `paper_id` | `uuid` | no |
| `kind` | `paper_kind` | no |
| `source` | `text` | yes |
| `title` | `text` | no |
| `authors` | `text[]` | no |
| `url` | `text` | yes |
| `external_id` | `text` | yes |
| `categories` | `text[]` | no |
| `updated_at` | `timestamptz` | yes |

## `arxiv_paper_metadata`  (1,841,240 rows)

arXiv-specific metadata, keyed by `arxiv_id` (which equals `paper.external_id` for arXiv rows). Holds abstract, bibliography (jsonb keyed by cite_key), parsed preamble, and reference graph. `in_validation` flags rows still being checked.

| column | type | null |
|---|---|---|
| `arxiv_id` | `text` | no |
| `journal_ref` | `text` | yes |
| `doi` | `text` | yes |
| `license` | `text` | yes |
| `abstract` | `text` | yes |
| `citation_count` | `int4` | yes |
| `reference_ids` | `text[]` | yes |
| `preamble` | `text` | yes |
| `bibliography` | `jsonb` | yes |
| `bibtex` | `bool` | yes |
| `in_validation` | `bool` | no |

## `lean_community_paper_metadata`  (21 rows)

Blueprint-project metadata for Lean community repos that ship a LaTeX blueprint (apap, pfr, carleson, sphere-packing, etc.). `src_path` is the blueprint TeX root inside the repo.

| column | type | null |
|---|---|---|
| `repo_slug` | `text` | no |
| `branch` | `text` | no |
| `src_path` | `text` | no |
| `preamble` | `text` | yes |
| `bibliography` | `jsonb` | yes |
| `bibtex` | `bool` | yes |

## `lean_repo_metadata`  (30 rows)

Lean repo build pins — toolchain, mathlib revision, git commit. Used to reproduce the formalization environment that produced `formal_metadata` rows.

| column | type | null |
|---|---|---|
| `repo_slug` | `text` | no |
| `repo_url` | `text` | yes |
| `lean_toolchain` | `text` | yes |
| `mathlib_rev` | `text` | yes |
| `git_commit` | `text` | yes |

## `statement`  (12,137,642 rows)

Core node table. Every theorem/lemma/definition/remark, formal or informal. `body` is the verbatim text (LaTeX for informal, Lean source for formal). `proof` is informal-only.

| column | type | null |
|---|---|---|
| `statement_id` | `uuid` | no |
| `paper_id` | `uuid` | no |
| `formality` | `formality_kind` | no |
| `kind` | `text` | no |
| `body` | `text` | no |
| `proof` | `text` | yes |

## `informal_metadata`  (11,749,537 rows)

Informal-side per-statement metadata. **`lean` is the blueprint `\lean{...}` annotation** — when populated it is the ground-truth bridge to one or more formal `decl_name`s (comma-separated). `pre_context`/`post_context` are the surrounding paragraph windows used by some slogan prompts.

| column | type | null |
|---|---|---|
| `statement_id` | `uuid` | no |
| `ordinal` | `int4` | no |
| `ref` | `text` | yes |
| `label` | `text` | yes |
| `note` | `text` | yes |
| `pre_context` | `text` | yes |
| `post_context` | `text` | yes |
| `lean` | `text` | yes |

## `formal_metadata`  (388,105 rows)

Formal-side per-statement metadata. `decl_name` is the fully-qualified Lean name — the natural key when matching to `informal_metadata.lean`. `is_instance` flags `instance` declarations.

| column | type | null |
|---|---|---|
| `statement_id` | `uuid` | no |
| `file_path` | `text` | yes |
| `decl_name` | `text` | yes |
| `module` | `text` | yes |
| `docstring` | `text` | yes |
| `is_instance` | `bool` | no |

## `informal_dependency`  (18,321,208 rows)

Informal edges. Each row is a (`src_id` → `dep_id`/`cite_id`) reference detected in the source paper. `methods` records *how* it was detected (deterministic / heuristic / LLM / judge); used by the `comprehensive` slogan prompt as a trust score.

| column | type | null |
|---|---|---|
| `src_id` | `uuid` | no |
| `location` | `text` | no |
| `cite_id` | `uuid` | yes |
| `cite_key` | `text` | yes |
| `dep_id` | `uuid` | yes |
| `dep_key` | `text` | yes |
| `dep_name` | `text` | yes |
| `methods` | `text[]` | no |

## `formal_dependency`  (11,335,708 rows)

Formal edges from Lean's elaborator. `edge_type` ∈ {def, proof, sig}: signature edges live in the type; def/proof edges live in the body. `position`/`binder`/`role` annotate signature edges (used by the ranker to prioritize structural args).

| column | type | null |
|---|---|---|
| `src_id` | `uuid` | no |
| `dep_id` | `uuid` | no |
| `edge_type` | `text` | no |
| `tactic_context` | `text` | yes |
| `position` | `text` | yes |
| `binder` | `text` | yes |
| `role` | `text` | yes |
| `via_proj` | `bool` | yes |

## `notation`  (23,017,529 rows)

Per-statement notation glossary (LaTeX pattern → English description). Generated downstream of slogan creation; used by retrieval to disambiguate symbols.

| column | type | null |
|---|---|---|
| `notation_id` | `uuid` | no |
| `statement_id` | `uuid` | no |
| `pattern` | `text` | no |
| `description` | `text` | no |
| `created_at` | `timestamptz` | no |

## `slogan_prompt`  (8 rows)

Immutable prompt-template registry. `slogan.prompt_name` foreign-keys here. Each template is a Jinja string consumed by the slogan generator.

| column | type | null |
|---|---|---|
| `name` | `text` | no |
| `template` | `text` | no |
| `created_at` | `timestamptz` | no |

## `slogan_model`  (2 rows)

LLM registry for slogan generation. `slogan.model_name` foreign-keys here.

| column | type | null |
|---|---|---|
| `name` | `text` | no |
| `model` | `text` | no |
| `temperature` | `float8` | yes |
| `max_tokens` | `int4` | yes |
| `created_at` | `timestamptz` | no |

## `slogan`  (16,468,862 rows)

The natural-language summary attached to a `statement` by (`prompt_name`, `model_name`). One statement can have many slogans (different prompts/models). `insufficient_context=true` means the LLM refused — these are excluded from embedding and matching.

| column | type | null |
|---|---|---|
| `slogan_id` | `uuid` | no |
| `statement_id` | `uuid` | no |
| `prompt_name` | `text` | no |
| `model_name` | `text` | no |
| `slogan` | `text` | no |
| `in_tokens` | `int4` | yes |
| `out_tokens` | `int4` | yes |
| `created_at` | `timestamptz` | no |
| `insufficient_context` | `bool` | no |

## `embedding_model`  (1 rows)

Embedding-model registry. `instruction` is prepended to slogan text at embed time (Qwen3 retrieval prefix). `dim` is the native dimensionality (4096 for qwen3-8b).

| column | type | null |
|---|---|---|
| `name` | `text` | no |
| `model` | `text` | no |
| `instruction` | `text` | yes |
| `dim` | `int4` | no |
| `normalized` | `bool` | no |
| `created_at` | `timestamptz` | no |

## `embedding`  (12,137,638 rows)

The vector store. One row per (`slogan_id`, `model_name`). `embedding` is `vector(4096)` for qwen3-8b. Indexed by binary-quantized HNSW (`bit(4096)`) for shortlist search and queried with cosine (`<=>`) for full-precision rerank.

| column | type | null |
|---|---|---|
| `embedding_id` | `uuid` | no |
| `slogan_id` | `uuid` | no |
| `model_name` | `text` | no |
| `embedding` | `vector` | no |
| `created_at` | `timestamptz` | no |

## `arxiv_parse_status`  (1,841,240 rows)

Per-arXiv parse-attempt log. `error` is NULL on success, otherwise a tagged reason ([EMPTY ERROR] for documents that parsed but yielded no statements). `parsing_method` is the parser used.

| column | type | null |
|---|---|---|
| `arxiv_id` | `text` | no |
| `last_parse_attempt_at` | `timestamptz` | no |
| `error` | `text` | yes |
| `parsing_method` | `text` | no |
| `validation_level` | `text` | no |
