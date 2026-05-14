CREATE TYPE formality_kind AS ENUM ('formal', 'informal', 'semiformal');

CREATE TABLE statement (
    statement_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id UUID NOT NULL REFERENCES paper(paper_id) ON DELETE CASCADE,
    formality formality_kind NOT NULL,
    kind TEXT NOT NULL,
    body TEXT,
    proof TEXT
);

COMMENT ON TABLE statement IS
'A single mathematical statement extracted from a paper or formal source.';

-- For formal rows, statement.body holds the lean-graph signature (the
-- pretty-printed type) and statement.proof holds the tactic_summary. The
-- extension table below carries only the location/identification fields plus
-- the docstring.
CREATE TABLE formal_metadata (
    statement_id  UUID PRIMARY KEY REFERENCES statement(statement_id) ON DELETE CASCADE,
    file_path TEXT,          -- path within the repo (NULL when unknown, e.g. unresolved decls)
    decl_name TEXT,          -- fully qualified declaration name (Lean FQN)
    module    TEXT,          -- defining Lean module (lean-graph nodes.module)
    docstring TEXT           -- Lean docstring from lean-graph statements.jsonl
);

COMMENT ON TABLE formal_metadata IS
'Extension table for formal statements (e.g. Lean). Join to statement on statement_id.';

CREATE TABLE informal_metadata (
    statement_id UUID PRIMARY KEY REFERENCES statement(statement_id) ON DELETE CASCADE,
    ordinal      INT NOT NULL,  -- 0-based position of this statement in document order
    ref TEXT, -- e.g. "3.2"
    label TEXT, -- LaTeX \label value
    note TEXT, -- env optional [] argument
    pre_context TEXT,
    post_context TEXT
);

COMMENT ON TABLE informal_metadata IS
'Extension table for informal statements (e.g. arXiv LaTeX). Join to statement on statement_id.';