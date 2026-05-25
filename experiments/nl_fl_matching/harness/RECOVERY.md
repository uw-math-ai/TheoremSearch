# Harness recovery cheat sheet

If you come back and find that local processes died (klone session expired,
node rebooted, /tmp wiped, anything else), here's how to resume cleanly.

## State of the world as of last sign-off (2026-05-25)

In-flight Aristotle projects (all on Harmonic's servers, 30-day retention):

| candidate | arm | project_id | task status at sign-off |
|---|---|---|---|
| A_martingale_iff_classDL | no_graph | `ddb6ae7f-4934-47f7-a730-afa2722214c4` | IN_PROGRESS (~3 hr) |
| A_martingale_iff_classDL | with_graph | `a8214974-c549-428c-8e64-6823e26795b9` | COMPLETE_WITH_ERRORS (digest pending; subagent on 2nd submit) |
| A_martingale_iff_classDL | with_graph (#2) | `a51b745a-0def-4785-a00f-58ad5b5512a2` | IN_PROGRESS |
| B_submartingale_iff_classDL | no_graph | `ac0d5abc-90d0-47e6-b925-1b603446c277` | ✅ **DONE** — partial; digest landed at `runs/B*_rescue.digest.json` |
| B_submartingale_iff_classDL | with_graph | `5cd4e9d0-cfa9-42f6-84b1-88edb13eec3f` | IN_PROGRESS |
| F_eta_def | both | (not started) | trivial; no `sorry` to prove |
| A/B aesop | both | (not started) | scaffolded but not fired |

## Recovery procedure

```bash
# 1. Re-establish env
module load coenv/python/3.13.11
export PATH=$HOME/.elan/bin:$HOME/.local/bin:$PATH
export ARISTOTLE_API_KEY=$(grep ^ARISTOTLE_API_KEY= /gscratch/amath/simku22/TheoremSearch/.env | cut -d= -f2-)
export RDS_HOST=theorem-search.cluster-cx0ei6kq0qcn.us-west-2.rds.amazonaws.com

# 2. See what's still running on Aristotle's side
cd /tmp/simku22/repos/brownian-motion 2>/dev/null || (
  mkdir -p /tmp/simku22/repos && cd /tmp/simku22/repos &&
    git clone --depth=1 --branch=v4.29.0 https://github.com/RemyDegenne/brownian-motion.git
)
uv run aristotle list --limit 20

# 3. For each project that's still IN_PROGRESS, re-attach a rescue:
cd /gscratch/amath/simku22/TheoremSearch
python3 -m experiments.nl_fl_matching.harness.rescue \
    --label A_martingale_iff_classDL --arm no_graph \
    --project-id ddb6ae7f-4934-47f7-a730-afa2722214c4 \
    --target-file /tmp/simku22/repos/brownian-motion/BrownianMotion/_Harness/A_martingale_iff_classDL__no_graph.lean \
    --project-dir /tmp/simku22/repos/brownian-motion \
    --existing-trajectory /gscratch/amath/simku22/TheoremSearch/experiments/nl_fl_matching/harness/runs/A_martingale_iff_classDL__no_graph__20260525T052648Z.jsonl

# Repeat for B no_graph (project ac0d5abc — but B is already done; check first)
# Repeat for A with_graph #2 (project a51b745a)
# Repeat for B with_graph (project 5cd4e9d0)
# Each rescue polls aristotle tasks every 60s, downloads the .tar.gz, writes a digest.

# 4. For projects already COMPLETE_WITH_ERRORS, you can skip the polling and
#    download directly:
uv run aristotle download <pid> --destination /gscratch/amath/simku22/TheoremSearch/experiments/nl_fl_matching/harness/runs/returned_proofs/<pid>.tar.gz
# Then untar into a sibling dir.

# 5. Promote everything to RDS
python3 -m experiments.nl_fl_matching.harness.promote

# 6. Run analyzer
python3 -m experiments.nl_fl_matching.harness.analyze_trajectories
```

## What's where

| artifact | location | survives /tmp wipe? |
|---|---|---|
| Trajectory JSONLs | `experiments/nl_fl_matching/harness/runs/*.jsonl` | ✅ /gscratch |
| Digest JSONs | `experiments/nl_fl_matching/harness/runs/*.digest.json` | ✅ /gscratch |
| Returned Lean proofs | `experiments/nl_fl_matching/harness/runs/returned_proofs/` (if copied) **OR** `/tmp/simku22/.../_rescue_*_unpacked/` | TODO: copy explicitly |
| Lake worktrees | `/tmp/simku22/repos/{brownian-motion,pfr}/` | ❌ recreate via `git clone --depth=1` |
| All harness code | in repo | ✅ pushed |
| RDS tables | `theorem-search.cluster-cx0ei6kq0qcn...` db `v2` | ✅ |
| Aristotle project results | Harmonic's servers | ✅ 30 days from project creation |

## Known issues

- `aristotle download` writes a single `.tar.gz`, not a directory (CLI help is misleading). `tools.aristotle_download` handles this; `rescue.py` uses it correctly.
- `aristotle tasks` is the fast non-streaming status check; `aristotle show` blocks indefinitely.
- Status enum includes `COMPLETE_WITH_ERRORS` (mapped to `partial` in our digest) — not in original docs.
- Local `lake build` of brownian-motion fails on klone due to a GLIBC mismatch with `clang`. Aristotle handles project build server-side, so the local build isn't needed for the harness — but it does mean we can't run `lean_typecheck` locally as a pre-flight (the subagent now treats this as an expected failure).

## Memory

Saved memory notes that future sessions auto-load:
- `feedback_agent_driven_harness.md` — preferred prover harness pattern
- `reference_aristotle_limits.md` — free preview, ~4 concurrent ceiling, no quota
- `feedback_grep_before_formalize.md` — verify candidates aren't already formalized via grep
- `reference_v2_rds_host.md` — RDS_HOST override (stale secret)
