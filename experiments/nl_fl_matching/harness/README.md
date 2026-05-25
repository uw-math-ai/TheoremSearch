# Aristotle harness — subagent-driven

For each (candidate, arm) pair, spawn a Claude subagent with tool access
to the `aristotle` CLI. The subagent drives the proof, with a hard
budget cap. Every tool call and response is appended to a JSONL
trajectory — that trajectory IS the experimental data (premise picks,
hint refinements, retry attempts), not just pass/fail.

## Why an agent loop, not a single submit

The recommended Aristotle interaction model (per the docs and per
guidance from the PI) is "Claude prompts Aristotle." That setup gets
us:

- **Trajectory as data**: every premise pick, every hint adjustment,
  every retry is captured. The paper's "graph helps prover" figure
  becomes richer — not just success rate but also "graph context →
  fewer iterations / shorter trajectories / different premise types."
- **Validates the production pattern**: we test the actual Claude→Aristotle
  interface, not a stripped-down single-shot.
- **Autonomy**: sweep all 326 candidates without sitting at a terminal.

## Layout

| file | purpose |
|---|---|
| `tools.py` | Python wrappers around `aristotle submit / ask / show`, plus local `read_target_file` / `write_target_file` / `lean_typecheck`. |
| `subagent.py` | One agent loop for one (candidate, arm). Uses the Anthropic SDK. |
| `orchestrator.py` | Sweeps the subagent across multiple candidates/arms. Stages each `.lean` file into the project worktree, hands the trajectory path to the subagent, summarizes after. |
| `promote.py` | Post-sweep: read `*.digest.json` files, filter to promotable statuses, write to RDS `prover_run`. JSONL trajectory paths are recorded but the raw turns stay on disk. |
| `prover_run_schema.sql` | RDS DDL for `prover_run`. |
| `targets/<candidate>/{no_graph,with_graph}.lean` | Per-candidate `.lean` pairs. (Currently `A_martingale_iff_classDL/` directly under `harness/`; will migrate to `targets/` when B and F land.) |
| `runs/` | JSONL trajectories + digest files. **Gitignored** (volume + sometimes-sensitive prompt content). |

## Budget (per (candidate, arm))

Hard limits enforced in `subagent.py`:
- `MAX_ARISTOTLE_SUBMITS = 2`
- `MAX_ARISTOTLE_ASKS = 1`
- `MAX_TURNS = 25` (subagent conversation turns; safety cap against loops)
- `SUBAGENT_MODEL = "claude-sonnet-4-6"` (cheaper than Opus for the agent loop)

These can be tuned in `subagent.py`. The Aristotle CLI does not expose
per-call cost / time caps — we'll learn empirical pricing once the
first runs land and tighten from there.

## Pre-run setup

```bash
# 1. Env vars in TheoremSearch/.env (gitignored)
#    ARISTOTLE_API_KEY=...    # from aristotle.harmonic.fun dashboard
#    BEDROCK_API_KEY=...      # AWS Bedrock bearer token; already populated
#    AWS_REGION=us-west-2     # already populated
# (The subagent uses Bedrock-hosted Claude — no ANTHROPIC_API_KEY needed.)
# Override the Bedrock model ID via SUBAGENT_MODEL env var; defaults to
# the latest Sonnet on Bedrock (us.anthropic.claude-sonnet-4-5-20250929-v1:0).

# 2. Install aristotle via uv tool (matches Harmonic's recommendation;
#    see https://aristotle.harmonic.fun/dashboard/docs)
uv tool install aristotlelib
# Invocation pattern is `uv run aristotle ...`. tools.py does this for
# you and runs with cwd=project_dir so uv finds aristotlelib correctly.

# 3. Anthropic SDK for the subagent
python3 -m pip install --user anthropic    # OR: uv add anthropic in a pyproject

# 4. Warm the brownian-motion build cache (once; takes ~30 min first time)
cd /tmp/simku22/repos/brownian-motion
lake build
```

## Run one (candidate, arm) end-to-end

```bash
RDS_HOST=theorem-search.cluster-cx0ei6kq0qcn.us-west-2.rds.amazonaws.com \
    python3 -m experiments.nl_fl_matching.harness.orchestrator \
        --candidates A_martingale_iff_classDL \
        --arms no_graph,with_graph \
        --project-dir /tmp/simku22/repos/brownian-motion
```

Then promote the good ones to RDS:

```bash
RDS_HOST=theorem-search.cluster-cx0ei6kq0qcn.us-west-2.rds.amazonaws.com \
    python3 -m experiments.nl_fl_matching.harness.promote
```

## Trajectory schema (JSONL, one row per kind)

| kind | when | key fields |
|---|---|---|
| `run_start` | once per run | run_id, candidate_label, arm, budget |
| `user_msg` | initial prompt | content |
| `assistant_msg` | each Claude response | stop_reason, usage, content (list of text + tool_use blocks) |
| `tool_call` | each tool invocation | tool, input, tool_use_id |
| `tool_result` | each tool result | tool, tool_use_id, result |
| `api_error` | Anthropic API failure | error |
| `run_end` | once per run | full digest |

## Analysis hooks (later)

Once `prover_run` has rows, the headline plots are SQL away:

```sql
-- Pass rate by arm
SELECT arm,
       COUNT(*) FILTER (WHERE status = 'proved') * 1.0 / COUNT(*) AS pass_rate,
       AVG(aristotle_submits) AS mean_submits,
       AVG(wall_time_s) AS mean_wall_s
  FROM prover_run
 GROUP BY arm;

-- Pass rate by arm × directed-distance bin
SELECT pr.arm, ca.distance_prereq_to_cons,
       COUNT(*) FILTER (WHERE pr.status = 'proved') * 1.0 / COUNT(*) AS pass_rate
  FROM prover_run pr
  JOIN candidate_attributes ca USING (statement_id)
 GROUP BY pr.arm, ca.distance_prereq_to_cons
 ORDER BY 1, 2;
```
