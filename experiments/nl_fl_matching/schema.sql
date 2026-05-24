-- Output store for the NL↔FL matching pilot.
-- One row per (query_statement, direction, exclusion, rank, embedding_model).
--
-- direction ∈ {'f2i','i2f','f2f','i2i'}
-- exclusion ∈ {'statement','paper'}   -- candidate filter applied during search
-- pool_descriptor: free-form tag for the candidate pool used
--                  ('all_informals' | 'project_formals' | 'blueprint_informals' | ...)
--
-- The PK lets each (query, direction, exclusion) write k rows without
-- collision. Re-runs overwrite by (query_statement_id, direction, exclusion,
-- rank, embedding_model) — see store.write_rows.

CREATE TABLE IF NOT EXISTS nl_fl_match_pilot (
    query_statement_id     uuid        NOT NULL,
    direction              text        NOT NULL,
    exclusion              text        NOT NULL,
    rank                   int         NOT NULL,
    candidate_statement_id uuid        NOT NULL,
    candidate_paper_id     uuid        NOT NULL,
    similarity             float8      NOT NULL,
    embedding_model        text        NOT NULL,
    pool_descriptor        text        NOT NULL,
    created_at             timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (query_statement_id, direction, exclusion, rank, embedding_model)
);

CREATE INDEX IF NOT EXISTS nl_fl_match_pilot_cand_idx
    ON nl_fl_match_pilot (candidate_statement_id);

CREATE INDEX IF NOT EXISTS nl_fl_match_pilot_dir_excl_idx
    ON nl_fl_match_pilot (direction, exclusion);
