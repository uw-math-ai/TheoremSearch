CREATE TYPE paper_kind AS ENUM ('lean_repo', 'paper', 'textbook', 'open_project', 'blueprint');

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
    reference_ids TEXT[], -- ARXIV (preferred) or DOI-prefixed ID (e.g. ARXIV:2109.06451)
    in_validation BOOLEAN NOT NULL DEFAULT FALSE
);

COMMENT ON TABLE arxiv_paper_metadata IS
'Extension table for arXiv papers. Join to paper on paper_id.';

CREATE TABLE lean_community_paper_metadata (
    repo_slug TEXT PRIMARY KEY, -- "owner/repo"; references paper(external_id) where source = 'Lean Community'
    branch TEXT NOT NULL, -- default branch of the repo at scrape time
    src_path TEXT NOT NULL, -- relative path inside the repo to the blueprint LaTeX source dir
    preamble TEXT,
    bibliography JSONB, -- Map of cite key -> {title?, arxiv_id?}
    bibtex BOOLEAN
);

COMMENT ON TABLE lean_community_paper_metadata IS
'Extension table for Lean Community blueprints. Stores the GitHub coordinates needed to re-fetch the LaTeX source plus the parsed preamble/bibliography. Join to paper on external_id.';

-- Project-level metadata for Lean repositories ingested via the lean-graph
-- pipeline (formalized_graph_v2). Keyed by the repo slug from the upstream
-- corpus DB (projects.name, e.g. "Mathlib", "apap") which becomes
-- paper.external_id when source='Lean Repo'.
CREATE TABLE lean_repo_metadata (
    repo_slug       TEXT PRIMARY KEY,    -- references paper(external_id) where source = 'Lean Repo'
    repo_url        TEXT,                -- upstream repo URL; populated manually
    lean_toolchain  TEXT,                -- e.g. "v4.29.0"
    mathlib_rev     TEXT,                -- Mathlib git revision pinned at extraction
    git_commit      TEXT                 -- this project's git revision at extraction
);

COMMENT ON TABLE lean_repo_metadata IS
'Extension table for Lean repositories ingested via lean-graph. Pins the toolchain/git revisions of the snapshot the corresponding statement/formal_metadata rows were extracted from. On ingest, paper.title = repo_slug and paper.updated_at = the snapshot timestamp (UTC). Join to paper on external_id.';