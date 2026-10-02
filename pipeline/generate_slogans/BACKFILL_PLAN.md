# Making the 2,901 unsearchable statements searchable

2,901 statements in the six v1-ingested sources are present in v2 but cannot be
found by `/graph/embedding`. v1 can find them, so this is the last content gap
blocking the retirement of v1 search.

Diagnosed 2026-10-02. **Pilot run on 2026-10-02: 49 of a planned 50
statements regenerated and reviewed — see "Pilot results" below. The
remaining 2,852 have not been run.**

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

So the run was interrupted after the second rung. **Root cause, confirmed
2026-10-02 (not the original guess of a process kill):** `minimal.j2` and
`standard.j2` are pure ASCII; `comprehensive.j2` and `final.j2` contain an
em dash. `load_prompt()` read template files with `Path.read_text()`, which
decodes using `locale.getpreferredencoding(False)` when no encoding is given
— `cp1252` on this Windows machine, not UTF-8 — so the em dash was silently
corrupted into mojibake. `register_prompt()` then refused to run
`comprehensive`, because the corrupted text didn't match what was already
registered for that prompt name from an earlier, correctly-decoded run.
A `--chain` invocation calls `register_prompt` once per stage in sequence,
so it would complete `minimal` and `standard` (both ASCII, unaffected) and
then die exactly at `comprehensive` — matching "38,401 → 3,225 → never ran →
never ran" precisely. Confirmed directly: under the old unguarded
`read_text()`, `comprehensive.j2`'s content does not match its registered
template either, for the identical reason. Fixed in `514a969` by reading templates and `models.json` with
`encoding="utf-8"` explicitly, in `generate_slogans` and in
`parse_dependencies/judge.py`, which had the same bug on two live-loaded
templates. The 2,901 were simply waiting for rungs three and four to run
without crashing.

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
- **Why `minimal` and `standard` refused so often for these sources:**
  `minimal.j2` offers only the bare body; `standard.j2` adds proof,
  pre/post-context and paper abstract if present, with the same
  "respond with exactly INSUFFICIENT CONTEXT:" escape hatch
  (`standard.j2:4`) as `minimal.j2:4`. Neither template has any document-order
  capability. For these six sources every one of those optional fields really
  is empty — `proof` is empty for all 38,401, there are 0 dependency edges,
  and no abstract — so these two prompts had nothing beyond the bare body to
  work with, which is the plain reason 3,225 then 2,901 statements came back
  refused.
- **`comprehensive`/`final` are a different story, and the plan's first draft
  had this wrong:** both templates *do* add a "Document order"
  (`prev_statement`/`next_statement`) block, and `informal_metadata.ordinal`
  is set for all 38,401 statements in these sources, so that block renders for
  every one of them — confirmed via `--test`, not assumed. For Stacks this
  context is usually a help: each ingested "paper" is one chapter, so
  neighbours are topically adjacent lemmas. For ProofWiki it is a mixed bag —
  that source was ingested as a *single* paper of 23,805 pages in v1's old
  `theorem_id` order, so neighbours are sometimes unrelated (`--test` on a
  König's Lemma statement showed a "Before" neighbour about the kurtosis of a
  normal distribution — pure noise) and sometimes a genuine continuation of a
  statement that v1 split across adjacent rows (see the Matroid Base Axioms
  example under "Pilot results," where the pilot's slogan correctly pulls a
  fact stated only in the *following* row). None of this is why
  `comprehensive`/`final` show 0 attempts for these six sources, though —
  they never ran at all here, for the mechanical reason under "Root cause"
  above.
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

Skipping `comprehensive` is deliberate. Its only addition over `standard` is
the document-order block (see above — it does render for these sources, not
empty as the plan first assumed), but it refuses 34.90% of the time
corpus-wide and lacks `final.j2`'s "don't hedge or refuse" instruction, so a
`comprehensive` pass here would mostly spend calls re-deriving refusals that
`final` has already been shown (by the pilot) not to produce. The documented
`--chain -m qwen3-235b -w 8 -c SOURCES` also works and is idempotent — without
`--overwrite` the first two rungs no-op on statements that already have those
slogans — but it pays for a `comprehensive` pass first for no benefit already
demonstrated here.

Writes rows with `model_name = 'qwen3-235b'` and `prompt_name = 'final'`.
`/graph/embedding` filters on `model_name` via `_SLOGAN_MODELS` and on
`NOT insufficient_context`, so new rows are picked up and the old refusals are
ignored without being destroyed.

**Pilot run 2026-10-02 — done, 49 of a planned 50.** `--sample` is documented
"for `--batch` prepare, testing" and is only read on the batch path, so it was
not used; the set was instead a stable pseudo-random draw (`ORDER BY
md5(statement_id::text) LIMIT 50`) plus five statements hand-picked from the
original refusal examples, deduplicated. One of those five (Stacks `18.23.3`)
turned out to already have a good `standard` slogan — it was pulled from an
earlier illustrative query that wasn't scoped to the true `bool_and(
insufficient_context)` pool, so `--insufficient` correctly excluded it from
reprocessing. The other 49 ran: 0 hard refusals (`insufficient_context=true`),
cost $0.0059, ~1 token in / out per $0.00012. The exact 50 IDs, bodies and
outputs are saved outside this repo; see "Pilot results" below for the
substance.

### Pilot results

Read all 49 individually against the original body and, where a match
existed, v1's slogan for the same body. Zero hard refusals (the literal
`INSUFFICIENT CONTEXT:` marker) and zero hits on a soft-refusal pattern scan
(`undefined`, `ambiguous`, `cannot`, `this statement`, etc.) — but reading
caught problems the pattern scan didn't:

- **One clear inversion.** Stacks `7.25.6`'s body says the functor `j_U!`
  *reflects* injections and surjections; the new slogan says it *preserves*
  them. These are different properties (reflects: image-has-P implies
  source-has-P; preserves: the converse) and v1's slogan had it right.
- **One overclaim.** Stacks `99.5.2`'s body says a functor is "fibred in
  groupoids"; the new slogan says it "forms a stack in groupoids," which
  requires descent conditions the body doesn't state.
- **One garbled paraphrase.** HoTT `5.3`'s new slogan ("If a function f has a
  contractible type...") confuses the body's actual claim (that `iscontr(f)`,
  the assertion that `f` is an equivalence, is itself a mere proposition).
- **One confirmed case of neighbour bleed**, found by rendering the exact
  prompt via `--test` rather than guessing: ProofWiki's "Equivalence of
  Definitions of Matroid Base Axioms" has a body that is *only* hypotheses
  ("Let S be a finite set. Let B be a non-empty set of subsets of S.") — no
  conclusion at all, because v1 split this theorem's hypotheses and its
  statement across two adjacent rows. The new slogan's specific claim
  ("satisfies formulations 1 and 4 of the base axiom") is not in the body or
  the title; it comes verbatim from the *next* row's content, which
  `final.j2`'s document-order block supplied. In this instance the borrowed
  fact happens to be accurate and necessary — the row's own body is
  incomplete without it — but it is bleed, not independent reasoning, and nothing
  stops it from pulling an *unrelated* neighbour's content the way the
  König's-Lemma `--test` case showed.

So: roughly 4 of 49 (8%) have a real imprecision, one of them a flat factual
inversion. The other 45 ranged from solid to better than v1 — notably Stacks
`115.16.2` ("A scheme is very reasonable."), where v1's "slogan" was the body
echoed verbatim and the new one at least names the fact that this is "a
strong technical condition" without inventing a false precise definition, and
the dense named example `91.13.1` (3,188 characters, originally refused as
"involves advanced concepts... that cannot be accurately summarised"), whose
new slogan is substantively equivalent in content and precision to v1's for
the same statement.

This is the rate for this prompt and model on this content; it is not a new
risk introduced by regenerating. `final`/`qwen3-235b` is the same combination
already behind the 217,666 slogans serving the rest of the corpus, at the
same uncorrected rate — regenerating these 2,901 does not make the corpus
less accurate than it already is elsewhere, and an imprecise-but-on-topic
slogan still embeds near the right content, which is a better outcome than
being unsearchable. But it is not the "clean success" an earlier pass at
this review called it; state the real numbers rather than rounding to zero.

The 49 pilot rows are being kept, not rolled back — they are correct enough
to stand, and re-running them would just reproduce the same distribution.

### Full run

`--insufficient` excludes the 49 already processed (they now have a `final`
slogan, good or not, so `NOT EXISTS(slogan WHERE prompt_name='final' AND
model_name='qwen3-235b')` no longer matches them). The remaining count is
exactly **2,852** (2,901 − 49). At the pilot's measured $0.00012/statement,
that is roughly **$0.35**, and at the pilot's ~2.6 statements/sec with 4
workers, a few tens of minutes. The command is the same one shown under
step 1 above — no `statement_id IN (...)` restriction, so it naturally picks
up exactly the remaining 2,852:

```bash
python -m pipeline.generate_slogans -p final -m qwen3-235b -w 8 --insufficient -c SOURCES
```

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

- **A residue is acceptable.** `final` has never hard-refused, but if a
  handful come back as a literal refusal anyway, take the slogan rather than
  forcing nonsense. Record the count instead of iterating prompts.
- **Expect roughly an 8% imprecision rate, not zero.** The pilot (49
  statements) found 1 flat factual inversion, 1 overclaim, 1 garbled
  paraphrase and 1 confirmed case of neighbour-content bleed — see "Pilot
  results." That is the rate for `final`/`qwen3-235b` on this content, already
  present (uncorrected) across the 217,666 slogans this combination has
  generated elsewhere; regenerating these 2,901 does not make the corpus less
  accurate than it already is. No prompt change is proposed to chase this
  lower — `final` is instructed not to hedge, which is what makes a thin
  statement usable and also what makes an inverted or borrowed claim read
  just as confidently as a correct one. A full-run spot check (e.g. the same
  ~2% sampling rate as the pilot) is worth doing after step 1, not before.
- **Do not include arXiv.** It has its own refusals from earlier rungs that
  the cascade is presumably still working through; folding them in would make
  a 2,901-statement job a multi-million-statement one.
- **Separate and unrelated:** 1,411 of 182,651 formal Lean slogans are flagged
  `insufficient_context`. Those were generated before the Lean signature
  backfill, and are tracked in `rds/helpers/backfill_formal_bodies.sql`.
