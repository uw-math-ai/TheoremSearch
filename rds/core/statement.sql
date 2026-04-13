CREATE TYPE formality_kind AS ENUM ('formal', 'informal', 'semiformal');

CREATE TABLE statement (
    statement_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id UUID NOT NULL REFERENCES paper(paper_id) ON DELETE CASCADE,
    -- repr_id UUID REFERENCES representation(repr_id) ON DELETE SET NULL,
    formality formality_kind NOT NULL,
    kind TEXT NOT NULL,
    body TEXT NOT NULL, -- statement as it appears in the source
    proof TEXT
);

COMMENT ON TABLE statement IS
'A single mathematical statement extracted from a paper or formal source.';

CREATE TABLE formal_metadata (
    statement_id  UUID PRIMARY KEY REFERENCES statement(statement_id) ON DELETE CASCADE,
    file_path TEXT NOT NULL, -- path within the repo
    decl_name TEXT, -- fully qualified declaration name
    tactic_summary TEXT -- summary of tactics used in proof
);

COMMENT ON TABLE formal_metadata IS
'Extension table for formal statements (e.g. Lean). Join to statement on statement_id.';

CREATE TABLE informal_metadata (
    statement_id UUID PRIMARY KEY REFERENCES statement(statement_id) ON DELETE CASCADE,
    ordinal      INT NOT NULL,  -- 0-based position of this statement in document order
    ref TEXT, -- e.g. "Theorem 3.2"
    label TEXT, -- LaTeX \label value
    note TEXT, -- env optional [] argument
    pre_context TEXT,
    post_context TEXT
);

COMMENT ON TABLE informal_metadata IS
'Extension table for informal statements (e.g. arXiv LaTeX). Join to statement on statement_id.';