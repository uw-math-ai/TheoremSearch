-- Directed dependency edge between two statements.
-- source_id "depends on" dep_id.
CREATE TABLE dependency (
    source_id       UUID NOT NULL REFERENCES statement(statement_id) ON DELETE CASCADE,
    cite_id         UUID REFERENCES paper(paper_id) ON DELETE CASCADE,
    dep_id          UUID REFERENCES statement(statement_id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,
    tactic_context  TEXT,       -- tactic that triggered this dependency (formal only)
    interpaper      BOOLEAN NOT NULL,
    cite_key        TEXT,       -- NULL for intrapaper citations
    dep_key         TEXT,       -- \label key (intrapaper) or \cite key (interpaper)
    dep_name        TEXT,       -- name as written in source, e.g. "Theorem A.1"
);

COMMENT ON TABLE dependency IS
'A directed dependency edge: source_id depends on dep_id.'