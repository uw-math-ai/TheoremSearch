-- Per-anchor informal-dependency neighborhood classifications.
-- Populated by experiments/nl_fl_matching/analysis/walk_neighborhoods.py.
-- One row per (anchor, k-hop, neighbor) triple.
--
-- Read this with `formalization_candidate_neighborhood` as the target
-- when looking for autoformalization candidates: status = 'none' or
-- 'annotated_only' rows are neighbors of an already-anchored statement
-- that themselves still need a Lean formalization.

CREATE TABLE IF NOT EXISTS formalization_candidate_neighborhood (
    anchor_statement_id   UUID NOT NULL,
    k                     SMALLINT NOT NULL,          -- 1 or 2 (k=2 excludes k=1)
    neighbor_statement_id UUID NOT NULL,
    status                TEXT NOT NULL,              -- resolved | annotated_only | matched_only | none
    lean_annotation       TEXT,                       -- raw informal_metadata.lean (comma-separated)
    n_decl_tokens         INT NOT NULL DEFAULT 0,
    n_decl_resolved       INT NOT NULL DEFAULT 0,
    resolved_decls        TEXT[] NOT NULL DEFAULT '{}',
    matched_sim           REAL,                       -- top-1 pilot sim (if any)
    matched_candidate_id  UUID,
    pool_descriptor       TEXT NOT NULL,              -- e.g. 'gold_subset_i2f' (anchors source)
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (anchor_statement_id, k, neighbor_statement_id)
);

-- Anchors join — quick filter by source pool.
CREATE INDEX IF NOT EXISTS idx_fcn_pool
    ON formalization_candidate_neighborhood (pool_descriptor);

-- Find anchors with formalized siblings AND unformalized neighbors.
CREATE INDEX IF NOT EXISTS idx_fcn_anchor_status
    ON formalization_candidate_neighborhood (anchor_statement_id, status);

-- Find unformalized neighbors by neighbor id (e.g. "is THIS neighbor
-- referenced by multiple anchors?").
CREATE INDEX IF NOT EXISTS idx_fcn_neighbor
    ON formalization_candidate_neighborhood (neighbor_statement_id);
