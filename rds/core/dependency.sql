-- Directed dependency edge between two statements.
-- source_id "depends on" dep_id.
CREATE TABLE dependency (
    source_id       UUID NOT NULL REFERENCES statement(statement_id) ON DELETE CASCADE,
    dep_id          UUID NOT NULL REFERENCES statement(statement_id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,
    tactic_context  TEXT,       -- tactic that triggered this dependency (formal only)
    interpaper      BOOLEAN NOT NULL,
    dep_key         TEXT,       -- \label key (intrapaper) or \cite key (interpaper)
    dep_name        TEXT,       -- name as written in source, e.g. "Theorem A.1"

    PRIMARY KEY (source_id, dep_id)
);

COMMENT ON TABLE dependency IS
'A directed dependency edge: source_id depends on dep_id.'

-- Tracks which papers a statement references by cite key,
-- with enough info to resolve the reference even if not yet ingested.
CREATE TABLE paper_reference (
    source_id   UUID    NOT NULL REFERENCES statement(statement_id) ON DELETE CASCADE,
    paper_id    UUID    REFERENCES paper(paper_id) ON DELETE SET NULL, -- nullable if unresolved
    cite_key    TEXT    NOT NULL,
    doi         TEXT,
    arxiv_id    TEXT,

    PRIMARY KEY (source_id, cite_key)
);

COMMENT ON TABLE paper_reference IS
'Records an external paper that a statement cites. paper_id may be NULL if the
referenced paper has not yet been ingested. cite_key is the in-source citation label.';