# Making the 2,901 unsearchable statements searchable

2,901 statements in the six v1-ingested sources are present in v2 but cannot be
found by `/graph/embedding`. v1 can find them, so this is the last content gap
blocking the retirement of v1 search.

Diagnosed 2026-10-02. Nothing below has been run yet.

## It is not template drift, and not missing data

The slogan pipeline is an **escalation cascade**: `--chain` runs
`minimal → standard → comprehensive → final`, and each later prompt re-attempts
only the statements whose every existing slogan is marked
`insufficient_context`. Across the whole corpus it works, and the last rung
resolves everything:

| prompt | slogans | refused | refusal rate |
|---|---:|---:|---:|
| `minimal` | 11,787,940 | 3,493,044 | 29.63% |
| `standard` | 3,493,036 | 626,641 | 17.94% |
| `comprehensive` | 623,744 | 217,666 | 34.90% |
| `final` | 217,666 | 0 | **0.00%** |

Each rung's input is the previous rung's refusals. For the six ingested
sources, the cascade stopped two rungs early:

| prompt | slogans | refused |
|---|---:|---:|
| `minimal` | 38,401 | 3,225 |
| `standard` | 3,225 | **2,901** |
| `comprehensive` | never ran | — |
| `final` | never ran | — |

So the run was interrupted after the second rung — consistent with the
process kills that interrupted other long jobs during this ingest. The 2,901
are simply waiting for rungs three and four.

Supporting evidence, all measured:

- **Every one of the 2,901 has slogans.** 0 are missing a slogan and 0 have a
  good slogan without an embedding, so no other stage is at fault. The funnel
  is `statement → slogan → embedding → statement_search → mv_search_*` and the
  loss is entirely at the slogan step.
- **They were already retried twice.** Stacks has 4,320 slogan rows for 2,048
  statements. A third attempt with the same prompt would refuse again.
- **The content is sloganable.** For 400 sampled refused Stacks bodies, v1 has
  a real slogan for **400 of 400**. v1 used DeepSeek-V3.1 with a body-only
  prompt and no refusal option, and it paraphrased around the `\ref{...}`
  cross-references ("as defined in a prior lemma") instead of giving up.
- **Why these sources and not arXiv:** `comprehensive.j2:6` offers the model an
  explicit way out — *"If you believe this is insufficient context ... respond
  with exactly INSUFFICIENT CONTEXT:"* — and its context block renders only if
  there is context to show. For these six sources there is none: `proof` is
  empty for all 38,401, they have 0 dependency edges, and no abstract. arXiv
  statements arrive with proof, pre/post context, abstract and neighbours, so
  the same prompt behaves completely differently.
- **`final.j2` already contains the fix** (line 6): *"If the context feels
  thin, make your best guess and write the slogan confidently — do not hedge,
  refuse, or mention missing context."* Hence its 0% refusal rate over 217,666
  statements.

The two refusal styles both fit this. Terse statements whose terms are defined
elsewhere — *"A scheme is very reasonable."* → *"The terms 'scheme' and 'very
reasonable' are undefined and lack mathematical context."* And dense ones the
model declines to compress — a ringed-topos statement → *"involves advanced
concepts ... that cannot be accurately [summarised]."* Neither is a data
problem; both are the escape hatch being taken.

## Plan

`SOURCES` below means:

```
"paper.source IN ('Stacks Project','ProofWiki','Open Logic Project','CRing Project','HoTT Book','An Infinitely Large Napkin')"
```

### 1. Regenerate the slogans with `final`

```bash
python -m pipeline.generate_slogans -p final -m qwen3-235b -w 8 --insufficient -c SOURCES
```

`--insufficient` restricts to statements whose every slogan is
`insufficient_context`, which is exactly the 2,901. 2,901 calls, no arXiv
statement touched.

Skipping `comprehensive` is deliberate: it refuses 34.90% of the time and its
value is the context block, which is empty for these sources, so it would
mostly spend calls to refuse again. The documented
`--chain -m qwen3-235b -w 8 -c SOURCES` also works and is idempotent — without
`--overwrite` the first two rungs no-op on statements that already have those
slogans — but it pays for a `comprehensive` pass first.

Writes rows with `model_name = 'qwen3-235b'` and `prompt_name = 'final'`.
`/graph/embedding` filters on `model_name` via `_SLOGAN_MODELS` and on
`NOT insufficient_context`, so new rows are picked up and the old refusals are
ignored without being destroyed.

**Pilot first.** Run with `--sample 50` and read the output before the full
pass. Stratify across Stacks, ProofWiki and HoTT and across body lengths —
the refused bodies run 15 to 4,077 characters, median ~109 (ProofWiki) to ~345
(Stacks). Accept only if refusals are ~0 and the slogans read correctly;
v1's slogan for the same body is a useful reference.

### 2. Embed the new slogans

```bash
python -m pipeline.generate_embeddings -m qwen3-8b -c SOURCES
```

`generate_embeddings` already filters `NOT slogan.insufficient_context`
(`pipeline/generate_embeddings/__main__.py:62`), so the new slogans become
eligible automatically and the old refusals stay excluded.

### 3. Load them into the search table

```bash
python rds/scripts/build_statement_search.py --load \
    --source "Stacks Project" --source "ProofWiki" --source "Open Logic Project" \
    --source "CRing Project" --source "HoTT Book" --source "An Infinitely Large Napkin"
```

Incremental and safe: the loader deletes and re-inserts per paper batch
(`DELETE FROM statement_search WHERE paper_id = ANY(...)`) and `--source`
scopes it to these papers. It does **not** rebuild the 21 GB table, and the
arXiv HNSW index is untouched.

No index rebuild is needed. The non-arXiv rows land in
`statement_search_bq_other_hnsw` (741 MB) and
`statement_search_other_filters`, both of which are maintained on insert.

### 4. Refresh the metadata views

```sql
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_search_source_stats;
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_search_authors_by_source;
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_search_tags_by_source;
```

Until this runs, the website's `/api/metadata` keeps serving the old per-source
counts (cached 7 days on top of that).

### 5. Verify

The funnel should come back clean — `no_slogan`, `only_insufficient` and
`good_but_unembedded` all zero, and `embedded` equal to `statements`:

```sql
WITH st AS (
  SELECT st.statement_id, p.source
    FROM statement st JOIN paper p ON p.paper_id = st.paper_id
   WHERE p.source IN ('Stacks Project','ProofWiki','Open Logic Project',
                      'CRing Project','HoTT Book','An Infinitely Large Napkin')
), sl AS (
  SELECT st.source, st.statement_id,
         count(s.slogan_id) FILTER (WHERE NOT s.insufficient_context) AS good,
         count(e.embedding_id) AS embeddings
    FROM st
    LEFT JOIN slogan s ON s.statement_id = st.statement_id AND s.model_name = 'qwen3-235b'
    LEFT JOIN embedding e ON e.slogan_id = s.slogan_id
   GROUP BY st.source, st.statement_id
)
SELECT source, count(*) AS statements,
       count(*) FILTER (WHERE good = 0)                    AS still_refused,
       count(*) FILTER (WHERE good > 0 AND embeddings = 0)  AS unembedded,
       count(*) FILTER (WHERE embeddings > 0)               AS embedded
  FROM sl GROUP BY source ORDER BY 2 DESC;
```

Then confirm end to end that a previously unsearchable statement is findable —
e.g. search for the content of Stacks `115.16.2` or `37.20.3` with
`sources=['Stacks Project']` and check its `statement_id` comes back.

Target per-source counts, which should then match v1 exactly:
ProofWiki 23,805 · Stacks 12,693 · Open Logic 745 · CRing 545 · HoTT 382 ·
Napkin 231 — 38,401 total, up from 35,500.

## Risks and judgement calls

- **A residue is acceptable.** `final` has never refused, but if a handful
  still come back thin, take the slogan rather than forcing nonsense. Record
  the count instead of iterating prompts.
- **Quality is the thing to watch, not throughput.** `final` is instructed not
  to hedge, which is what makes it useful here and also what makes a bad
  slogan confident. Pilot output deserves real reading, especially for the
  dense ringed-topos statements where a confident wrong summary is worse for
  retrieval than none.
- **Do not include arXiv.** It has its own refusals from earlier rungs that
  the cascade is presumably still working through; folding them in would make
  a 2,901-statement job a multi-million-statement one.
- **Separate and unrelated:** 1,411 of 182,651 formal Lean slogans are flagged
  `insufficient_context`. Those were generated before the Lean signature
  backfill, and are tracked in `rds/helpers/backfill_formal_bodies.sql`.
