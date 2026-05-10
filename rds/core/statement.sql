CREATE TYPE formality_kind AS ENUM ('formal', 'informal', 'semiformal');

-- statement.kind value domain mirrors lean-graph's DeclarationType.label
-- (see formalized_graph_v2/lean-graph/ImportGraph/Types.lean).
-- Informal-source kinds (e.g. LaTeX 'lemma', 'corollary', 'conjecture') must be
-- normalized at ingest: lemma/corollary -> 'thm', conjecture -> 'other'.
CREATE TABLE statement (
    statement_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id UUID NOT NULL REFERENCES paper(paper_id) ON DELETE CASCADE,
    formality formality_kind NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN (
        'thm', 'def', 'ind', 'ctor', 'quot', 'rec',
        'inst', 'struct', 'class', 'opaque', 'axiom', 'other'
    )),
    -- Verbatim source text. Pinned NULL-able for now: lean-graph supplies only
    -- signature/docstring (see formal_metadata), no body. Stage 1 extractor will
    -- populate this for formal rows once wired up; informal rows fill it directly.
    body TEXT,
    proof TEXT
);

COMMENT ON TABLE statement IS
'A single mathematical statement extracted from a paper or formal source.';

CREATE TABLE formal_metadata (
    statement_id  UUID PRIMARY KEY REFERENCES statement(statement_id) ON DELETE CASCADE,
    file_path TEXT NOT NULL, -- path within the repo
    decl_name TEXT, -- fully qualified declaration name (Lean FQN)
    module TEXT, -- defining Lean module (lean-graph nodes.module)
    signature TEXT, -- pretty-printed type from lean-graph statements.jsonl
    docstring TEXT, -- Lean docstring from lean-graph statements.jsonl
    tactic_summary TEXT -- summary of tactics used in proof
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