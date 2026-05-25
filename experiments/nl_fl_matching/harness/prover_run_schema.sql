-- Prover-run results from the subagent-driven Aristotle harness.
-- One row per (candidate_id, arm, attempt_n) after a JSONL trajectory has
-- been "promoted" by promote.py (i.e., the run completed cleanly enough
-- that the digest is meaningful — not crashed mid-loop).
--
-- Raw turn-by-turn trajectories live as JSONL files under
-- experiments/nl_fl_matching/harness/runs/ (gitignored).

CREATE TABLE IF NOT EXISTS prover_run (
    run_id                  UUID PRIMARY KEY,
    candidate_statement_id  UUID NOT NULL,
    candidate_label         TEXT NOT NULL,           -- e.g. 'A_martingale_iff_classDL'
    arm                     TEXT NOT NULL,           -- 'no_graph' | 'with_graph'
    attempt_n               INT NOT NULL,            -- 1, 2, 3, ... if we rerun
    prover                  TEXT NOT NULL,           -- 'aristotle'
    prover_version          TEXT,
    subagent_model          TEXT,                    -- e.g. 'claude-sonnet-4-6'

    -- outcome
    status                  TEXT NOT NULL,           -- 'proved'|'partial'|'failed'|'error'|'budget_exhausted'
    sorry_count_initial     INT,
    sorry_count_final       INT,
    proved_axiom_free       BOOLEAN,                 -- result of #print axioms check (NULL if not run)

    -- agent loop stats
    aristotle_submits       INT NOT NULL DEFAULT 0,
    aristotle_asks          INT NOT NULL DEFAULT 0,
    subagent_turns          INT NOT NULL DEFAULT 0,
    wall_time_s             REAL,
    subagent_tokens_in      INT,
    subagent_tokens_out     INT,

    -- artifacts
    trajectory_jsonl_path   TEXT NOT NULL,           -- absolute path; gitignored
    final_lean_source       TEXT,                    -- the returned proof body (truncated)

    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (candidate_statement_id, arm, attempt_n)
);

CREATE INDEX IF NOT EXISTS idx_pr_candidate ON prover_run (candidate_statement_id);
CREATE INDEX IF NOT EXISTS idx_pr_arm_status ON prover_run (arm, status);
CREATE INDEX IF NOT EXISTS idx_pr_label_arm ON prover_run (candidate_label, arm);
