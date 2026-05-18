CREATE TABLE notation (
    notation_id  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    statement_id UUID        NOT NULL REFERENCES statement(statement_id) ON DELETE CASCADE,
    pattern      TEXT        NOT NULL,
    description  TEXT        NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (statement_id, pattern)
);

CREATE INDEX notation_statement_idx ON notation (statement_id);

COMMENT ON TABLE notation IS
'Notation introduced by a statement: one row per (statement, pattern). '
'Acts as a dictionary — look up by statement_id to get all notation it defines, '
'or scan pattern/description for app-side tooltip resolution.';
