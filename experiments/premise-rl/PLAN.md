# Premise Selection RL — Smoke Test Plan

## Goal
Produce Python code that runs GPT-5.4 with a premise-selection system prompt over the TheoremSearch REST API, on the 100 theorems in the `rl_test_100` Postgres table, and writes a JSON summary with statement-level recall@k plus full trajectory dumps. The agent's deliverable ends at code that runs end-to-end locally; the user wraps it in a SLURM script and submits to Hyak following AMATH protocols.

This is plumbing validation, not a publishable result. The point is to surface bugs (ID-mapping breakdown, prompts not being applied, cache silently broken, model spamming the same query) before scaling to training.

## Out of scope for this plan
- RL training (GRPO, fine-tuning) — comes Week 2+.
- Untrained baseline, full val split, additional frontier models.
- Paper-level (lenient) recall scoring — see "Scoring notes" below.
- SLURM scripts, Hyak environment setup, job submission — user handles all of this.

## Repo layout

The repo already has database helpers (`db.py` with `rds_conn` context manager, AWS Secrets Manager integration). Reuse them; do not write new connection code.

```
premise-rl/                  # new code lives here
  src/
    data/
      load_targets.py        # uses existing rds_conn, fetches target + dep data
      id_mapping.py          # search-API integer theorem_id <-> Postgres statement_id UUID
                             # via rapidfuzz body-similarity matching
    env/
      search_client.py       # POST /search wrapper + diskcache
      environment.py         # MDP: reset, step, reward, trajectory log
      prompts.py             # state -> string formatter
    policies/
      gpt54_prompted.py      # GPT-5.4 with premise-selection system prompt
    eval/
      run_eval.py            # main entry point; produces summary.json
      metrics.py             # recall@k, FP rate, mapping diagnostics
  configs/
    smoke_test.yaml          # H=5, k=10, alpha=0.1, beta=10, concurrency=32,
                             # match_threshold (set after calibration),
                             # cache_dir, results_dir
    prompts/
      premise_selection.txt  # system prompt (user-provided, do not modify)
  scripts/
    calibrate_threshold.py   # one-off: pick match_threshold for id_mapping
  tests/
    test_environment.py      # reward math on canned results
    test_search_client.py    # cache hit on second call
    test_id_mapping.py       # round-trip integer <-> UUID via body match
  pyproject.toml
  README.md
  .env.example               # OPENAI_API_KEY, AWS_REGION, RDS_SECRET_ARN, RDS_HOST
```

## Phase 1 — Data layer

The 100 target IDs already exist in Postgres as `rl_test_100`. The agent does not re-run the sampling SQL; it reads from the table directly.

1. Reuse the existing `db.py` helpers (`rds_conn`, `get_pool`). Do not write new connection code. The dbname is `v2`: call `rds_conn(dbname="v2")`.

2. `load_targets.py`: three queries returning Python dataclasses. The data load is one-time at startup so sync (psycopg2 via `rds_conn`) is fine even though the rest of the pipeline is async.

   **(a) Target statements:**
   ```sql
   SELECT s.statement_id, s.body, s.proof, s.kind, s.paper_id,
          im.label, im.ref, im.pre_context, im.post_context
   FROM rl_test_100 t
   JOIN statement s ON s.statement_id = t.src_id
   LEFT JOIN informal_metadata im ON im.statement_id = s.statement_id;
   ```

   **(b) True dependency edges** (statement-level only — `dep_id IS NOT NULL`):
   ```sql
   SELECT d.src_id, d.dep_id, d.cite_key, d.dep_name, d.dep_key
   FROM informal_dependency d
   JOIN rl_test_100 t ON t.src_id = d.src_id
   WHERE d.cite_key IS NOT NULL
     AND d.method = 'deterministic'
     AND d.dep_id IS NOT NULL;
   ```

   **(c) Dep statement bodies** (used for both trajectory inspection AND the body-similarity match in Phase 2.2):
   ```sql
   SELECT DISTINCT s.statement_id, s.body, s.kind, s.paper_id
   FROM informal_dependency d
   JOIN rl_test_100 t ON t.src_id = d.src_id
   JOIN statement s ON s.statement_id = d.dep_id
   WHERE d.cite_key IS NOT NULL
     AND d.method = 'deterministic'
     AND d.dep_id IS NOT NULL;
   ```

3. Build `theorem_id -> Target(body, proof, kind, label, ref, pre_context, post_context, true_dep_ids: set[UUID])`. Cache to a local pickle so the agent isn't re-querying Postgres on every dev iteration.

**Checkpoint:** print stats — number of targets loaded (should be 100), distribution of `len(true_dep_ids)` per target (all should be ≥2), total unique dep IDs across all targets (this is the size of the true-dep universe used for matching in Phase 2.2).

## Phase 2 — TheoremSearch REST client + ID mapping

The TheoremSearch API is documented at https://www.theoremsearch.com/docs. Base URL `https://api.theoremsearch.com`. Public — no auth header.

### 2.1 — REST client

`search_client.py`: async wrapper around `POST /search` exposing one method:
```python
async def search(query: str, k: int) -> list[SearchResult]
```
Where `SearchResult` mirrors the API's per-theorem response object: `theorem_id (int), slogan_id (int), name, body, slogan, theorem_type, link, similarity, paper`.

Request payload: `{"query": query, "n_results": k}`. Do not expose the rich filter parameters (`sources`, `types`, `tags`, `year_range`, `citation_range`, etc.) to the policy in this smoke test — keeping the action space minimal makes the trained policy comparable later.

Use `httpx.AsyncClient` with connection pooling. Diskcache backend keyed on `(query, k)`; cache dir from config. Retries with exponential backoff (3 attempts, 30s timeout). On persistent failure, log warning and return empty list — never raise into a rollout.

### 2.2 — ID mapping via body-similarity matching

The `/search` endpoint returns `theorem_id` as an **integer**. Postgres `statement.statement_id` is a **UUID**. There is no clean mapping between the two namespaces, so we resolve via Levenshtein-ratio matching over LaTeX bodies. Both sides come from the same extraction pipeline, so true matches should have very high character-level overlap; the ratio threshold separates true matches from coincidental overlap.

**Library:** `rapidfuzz` (NOT `python-Levenshtein`). C++-backed, ~50× faster, same API. Use `rapidfuzz.fuzz.ratio` which returns 0-100 normalized for length.

#### 2.2.a — Body normalization

Before any comparison, run both bodies (API and Postgres) through one normalizer. Differences in formatting are noise that depresses ratios for true matches.

```python
def normalize(body: str) -> str:
    body = re.sub(r"\\label\{[^}]*\}", "", body)   # strip \label{...}
    body = html.unescape(body)                       # & -> & etc.
    body = re.sub(r"\s+", " ", body)                 # collapse whitespace
    body = body.strip().rstrip(".")                  # strip trailing period
    return body
```

Lowercase is **not** safe — LaTeX is case-sensitive (`\Theta` ≠ `\theta`). Do not lowercase.

#### 2.2.b — Threshold calibration (BEFORE running rollouts)

`scripts/calibrate_threshold.py`: a one-off script that picks `match_threshold` empirically.

1. Sample 50 statements from Postgres that are likely to be in the API's index. Use `rl_test_100`'s true-dep set as the candidate pool — these are deterministic-citation targets, so they have stable identifiers and well-formed bodies.
2. For each, query the API with the statement's slogan (or body's first ~100 chars if no slogan) at `k=10`.
3. For each API result returned, compute `rapidfuzz.fuzz.ratio(normalize(api.body), normalize(pg.body))` against the source statement.
4. Identify the **true-match distribution**: for each query, the highest-ratio API result is presumed the true match (verify a few manually). Collect those ratios.
5. Identify the **cross-pair distribution**: ratios of API results that are NOT the source statement, against the source's Postgres body. These are coincidental overlap.
6. Plot/print both distributions. Pick `match_threshold` between the 5th percentile of true matches and the 95th percentile of cross-pairs. Write to `configs/smoke_test.yaml`.

**Go/no-go check:** if the 5th-percentile true match is below the 95th-percentile cross-pair, the distributions overlap and there is no clean threshold. **Stop.** Likely causes: parser-version skew between the API's snapshot and current Postgres (bodies extracted differently), or the API was indexed against a substantively different version of the corpus. Report findings and ask before proceeding.

Expected if all is well: true matches cluster ≥95, cross-pairs cluster ≤50, threshold around 85-90.

#### 2.2.c — Matcher implementation

`id_mapping.py`: at construction time, takes the union of true-dep bodies across all 100 targets (this is the full set of UUIDs we care about scoring against), normalizes each, and stores them. Exposes:

```python
def map_int_to_uuid(api_result: SearchResult) -> UUID | None:
    """Returns the UUID of the matching true-dep statement, or None if no match
    crosses match_threshold. Also logs the match score and the gap to the
    second-best match."""
```

Per-call cost: O(|true_deps_universe|) ratio computations, ~3K at most. rapidfuzz handles this in low single-digit milliseconds. No further optimization needed for the smoke test.

**Important:** matching against ONLY the true-dep universe (not all of Postgres) is the right scope. False positives don't need a UUID — they only need to be flagged as "not a true dep," which is the default if the matcher returns None. This keeps the matcher fast and avoids false-positive matches against unrelated statements that happen to share boilerplate LaTeX.

**Tiebreak / low-confidence flagging:** if the best match crosses threshold but the second-best is within a configurable gap (default 5 ratio points), log this as a low-confidence match in the trajectory. Track the rate as a metric.

#### 2.2.d — Tests

`tests/test_id_mapping.py`:
- **Round-trip test:** pick 5 statements from `rl_test_100`'s true-dep set. Query the API for their slogans. Verify the matcher recovers the correct UUIDs.
- **No-match test:** create a fake `SearchResult` with body "this is not a real theorem" and verify the matcher returns None.
- **Normalizer idempotence:** `normalize(normalize(x)) == normalize(x)` for various LaTeX inputs.

Do not proceed past Phase 2 until both calibration succeeds (clean threshold gap exists) and the round-trip test passes.

**Checkpoint:** `tests/test_search_client.py` calls `search("group homomorphism", 5)`, asserts non-empty results. `tests/test_id_mapping.py` round-trip passes. Calibration script's threshold and the two distributions are recorded in a results file for later reference.

## Phase 3 — Environment

1. `environment.py`: `PremiseSelectionEnv` class.
   - `reset(target_id) -> state`: loads target, sets `retrieved_uuids = set(), query_history = [], step_idx = 0, true_deps = target.true_dep_ids`.
   - `async step(query) -> (state, reward, done, info)`: calls `search_client.search`, runs each result through `id_mapping.map_int_to_uuid`, computes `new_uuids = {u for u in mapped if u is not None} - retrieved_uuids`, scores reward on **only** new UUIDs, updates state, increments step_idx. Done when `step_idx == H`.
   - Reward: per-step `|new ∩ true_deps| − α · |new \ true_deps|`. Terminal bonus added on the final step: `β · (|retrieved_uuids ∩ true_deps| / |true_deps|)`.
   - **Note on FPs:** an API result that fails to map to any UUID is **not** scored as a false positive — we don't know what it is. It's logged but excluded from reward. This keeps the FP penalty meaningful (a true FP is a confident match to a non-dep).
   - Trajectory log per episode: list of `{step, query, returned_results: [{int_id, mapped_uuid, match_score, second_best_gap}], new_tps, new_fps, dropped_no_match, step_reward, terminal_reward}`. Log both ID forms — debugging an ID-mapping issue later is much easier with the raw API IDs preserved.

2. `prompts.py`: `format_state(state) -> str`. Lays out target slogan + body + (optionally) pre/post context, prior queries, and prior retrieved slogans (not full bodies — too long). One place, used by the policy and any debugging.

**Checkpoint:** `tests/test_environment.py` with a fake search client returning canned results. Test cases:
- 3-step episode, mix of TPs and FPs across steps, asserts cumulative reward matches hand-computed value.
- Duplicate query case: same query issued twice. Second issuance must return zero new TPs and zero new FPs (reward = 0). Most common reward-shaping bug; do not skip.
- Terminal bonus only fires once, on the last step.
- Mapping failures: API result whose body matches nothing in the true-dep universe is logged as `dropped_no_match`, contributes zero reward and zero penalty, episode continues.

## Phase 4 — GPT-5.4 prompted policy

1. `configs/prompts/premise_selection.txt`: system prompt. The user has provided this — do not modify.

2. `gpt54_prompted.py`: one async function `run_episode(env, target_id, client, config) -> trajectory_dict`.
   - Pin model snapshot from config (`gpt-5.4-2026-03-05` or whichever dated snapshot is current). Do not use the `gpt-5.4` alias — it drifts.
   - Use the OpenAI Responses API with native tool use. Define one tool: `search_theorems(query: string, k: integer)`. Each tool call is wrapped into `env.step(query)`; the returned slogans (not full bodies) are passed back as the tool result message.
   - Maintain full conversation history across turns. Do not re-prompt with state — let the model see its own prior tool calls and results.
   - Termination: model declines to call the tool, OR `env` returns `done=True`, OR safety cap of `H` tool calls reached.
   - Temperature = 0 for reproducibility (and so the diskcache hits on re-runs).

3. **Async batching with concurrency 32.** OpenAI tier headers indicate 10K RPM / 10M TPM (Tier 5). The smoke test issues ~600 model calls total (100 episodes × ~6 turns); concurrency is about latency, not rate-limit avoidance. Use `asyncio.gather` with a semaphore at 32. If the API returns 429s anyway, halve and retry; the cap is generous enough that this shouldn't happen.

**Checkpoint:** run on a single target end-to-end. Manually inspect the trajectory JSONL:
- Are queries varied across steps, or is the model spamming the same query? Spam = state formatter isn't surfacing query history clearly enough. Fix before scaling.
- Is the model using prior retrieved slogans to refine? If queries ignore prior results, the prompt isn't conveying multi-step search.
- Is the model querying for restatements of the target (semantic neighbors) instead of likely lemma names (logical predecessors)? This is the central failure mode — and the diagnostic that motivates RL training.
- `dropped_no_match` rate per episode — should be moderate (most API results won't be in this target's true-dep set, so most won't match anything). High `low_confidence_match_rate` is a worse signal — investigate.

## Phase 5 — Evaluation

1. `metrics.py`: pure functions over trajectory JSONL.
   - `recall_at_k`: per-target `|retrieved_uuids ∩ true_deps| / |true_deps|`.
   - `mean_queries_per_episode`, `unique_query_rate`, `mean_FP_per_episode`, `mean_terminal_reward`.
   - `dropped_no_match_rate`: fraction of API results that didn't cross threshold against any true dep. Expected to be high (most results aren't in any of the 100 targets' dep sets) — this is informational, not an alarm.
   - `low_confidence_match_rate`: fraction of accepted matches where the gap to second-best was small. If this is >5%, recall numbers have meaningful uncertainty and should be reported with a caveat.

2. `run_eval.py`: takes a config, loads the 100 targets via Phase 1, builds the matcher via Phase 2, runs the policy concurrently, writes `<results_dir>/trajectories.jsonl` and `<results_dir>/summary.json`. `results_dir` is configurable so the user can point it at Hyak scratch when submitting.

3. Stratify summary by `len(true_deps)` bucket: `{2}, {3}, {4-5}, {6+}`. Averages over 100 mixed-dep-count theorems will be noisy; the bucket breakdown is where the signal lives.

**Checkpoint:** smoke run produces both files. Open `summary.json` and confirm:
- recall > 0 (if at the floor, suspect calibration first — re-check threshold, re-run round-trip test).
- `mean_queries_per_episode` close to H (model is using its budget).
- `unique_query_rate` > 0.7 or so (model isn't trivially repeating).
- `low_confidence_match_rate` < 5%.

## Scoring notes

This smoke test uses **statement-level recall only** — i.e., scores against `dep_id IS NOT NULL` edges. The corpus also contains a much larger pool of inter-paper edges where the citation was resolved to a *paper* but not to a specific statement (`cite_id IS NOT NULL, dep_id IS NULL`). Those are not used here.

For the full eval phase (Week 7), a two-tier scoring scheme is planned:
- **Strict (statement-level):** as implemented here. Headline number.
- **Lenient (paper-level):** retrieved statement counts as a hit if its `paper_id` matches a cited `cite_id`. Robustness check on a larger pool.

The lenient tier is not implemented in this plan to keep the smoke test focused. Don't add it unless asked.

## Configurability for Hyak submission

The user submits to Hyak manually. The agent's job is to make that easy by ensuring everything runs from configuration:

- **Cache dir, results dir:** read from `configs/smoke_test.yaml`. User points these at scratch (e.g. `/gscratch/<lab>/<user>/premise-rl/cache` and `.../results`) when running on Hyak.
- **Concurrency:** read from config. Tunable if rate limits change.
- **Secrets:** read from environment (`OPENAI_API_KEY`, `AWS_REGION`, `RDS_SECRET_ARN`, `RDS_HOST`). Document in `.env.example` and README. The user sources `.env` from their SLURM script; the agent does not need to know how.
- **Single entry point:** `python -m src.eval.run_eval --config configs/smoke_test.yaml` runs end-to-end. The agent verifies this works on a small subset before declaring done.

## Sanity checks (post-run, after user submits)

1. **Recall is non-trivial.** If recall is ~0, suspect (in order): threshold too strict (re-run calibration), prompt not loaded, temperature non-zero causing cache misses, search API returning empty results.
2. **Cache hits on re-run.** Second identical run should be near-100% cache hit. If not, queries are nondeterministic or cache key is wrong.
3. **Episode length.** Most episodes should hit H queries. If many bail at step 1-2, the prompt isn't conveying that multi-step refinement is expected.
4. **Trajectory eyeball.** Pick 5 trajectories — one each from {2}, {3}, {4-5}, {6+} buckets and one random. Read them. Are queries plausible? Is the model refining based on prior retrieved slogans? Is it searching for likely lemmas or for restatements of the target? The last is the central diagnostic.
5. **Low-confidence match audit.** If `low_confidence_match_rate` > 5%, manually inspect a sample of low-confidence matches. Are they real but with parser-formatting drift? Or are they spurious overlaps? Adjust normalizer or threshold accordingly.
6. **Cost report.** Total OpenAI spend for the 100-theorem run, extrapolated to the full val split size.

## Handoff prompt for the Claude Code Agent

> Implement Phases 1–5 of `PLAN.md` in order. Stop at each checkpoint and report results before continuing. Reuse the existing `db.py` (`rds_conn` context manager with `dbname="v2"`) — do not write new connection code. Use `uv` for dependency management, `httpx` (async) for the TheoremSearch REST API, and `rapidfuzz` (not `python-Levenshtein`) for body matching. Write tests for the environment reward math (Phase 3), the search client cache (Phase 2.1), and the ID mapping (Phase 2.2.d) before integrating with the OpenAI API. **Phase 2.2.b (threshold calibration) is a hard gate** — if calibration shows overlapping distributions with no clean threshold, stop and report. End goal: `python -m src.eval.run_eval --config configs/smoke_test.yaml` runs end-to-end on the 100 theorems in `rl_test_100` and writes `summary.json` to the configured results directory. Do not write SLURM scripts or Hyak-specific setup — the user submits manually. Do not implement training, untrained baselines, paper-level scoring, or full val-split evaluation — those are out of scope.
