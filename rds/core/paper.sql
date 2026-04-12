CREATE TYPE paper_kind AS ENUM ('lean_repo', 'paper', 'textbook', 'open_project');

CREATE TABLE paper (
    paper_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind paper_kind NOT NULL,
    source TEXT, -- overarching source of this paper (e.g. arXiv), NULL if unecessary
    title TEXT NOT NULL,
    authors TEXT[] NOT NULL DEFAULT '{}',
    url TEXT,
    external_id TEXT, -- paper ID within its source (e.g. arXiv ID, mathlib4 path)
    categories TEXT[] NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ, -- last time source content could have changed

    UNIQUE (source, external_id)
);

COMMENT ON TABLE paper IS
'A corpus of mathematical statements meant to be presented together.';
-- Two sources are distinct when a citation between them would be appropriate
-- e.g. a single arXiv paper, the entire Stacks Project, or a Lean repo

CREATE TABLE arxiv_paper_metadata (
    arxiv_id TEXT PRIMARY KEY, -- references paper(external_id)
    journal_ref TEXT,
    doi TEXT,
    license TEXT,
    abstract TEXT,
    preamble TEXT,
    bibliography JSONB, -- Map of cite key -> {title?, arxiv_id?}
    bibtex BOOLEAN,
    citation_count int,
    reference_ids TEXT[] -- ARXIV (preferred) or DOI-prefixed ID (e.g. ARXIV:2109.06451)
);

COMMENT ON TABLE arxiv_paper_metadata IS
'Extension table for arXiv papers. Join to paper on paper_id.';