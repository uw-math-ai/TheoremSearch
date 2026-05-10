-- Symmetric "these two statements are linked, here's why" table.
--
-- Distinct from informal_dependency / formal_dependency: dependency edges mean
-- "X uses Y" (directed, structural), while a link means "X and Y are the same
-- mathematical statement said differently" (symmetric, semantic).
--
-- Symmetry is enforced by requiring a_id < b_id (UUID order) so each unordered
-- pair has exactly one canonical row. The same pair can carry multiple
-- relation rows (e.g. both 'fl_nl_match' and 'collapse'); the PK includes
-- relation to allow that.
--
-- relation vocabulary (open TEXT, examples):
--   'fl_nl_match'  - formal Lean statement <-> informal restatement
--   'collapse'     - two informal statements that are the same theorem
--   'equiv'        - mathematically equivalent statements
--   'restatement'  - same content, different phrasing
CREATE TABLE statement_link (
    a_id        UUID NOT NULL REFERENCES statement(statement_id) ON DELETE CASCADE,
    b_id        UUID NOT NULL REFERENCES statement(statement_id) ON DELETE CASCADE,
    relation    TEXT NOT NULL,
    confidence  REAL,                   -- if produced by a model/heuristic
    source      TEXT,                   -- 'manual' | 'embedding' | 'name_match' | ...
    note        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (a_id, b_id, relation),
    CHECK (a_id < b_id)
);

COMMENT ON TABLE statement_link IS
'Symmetric semantic links between statements (FL<->NL match, collapse, equiv). '
'Pairs are stored canonically with a_id < b_id; one row per (pair, relation).';
