CREATE TABLE paper (
    id TEXT NOT NULL,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    license TEXT,
    authors TEXT[] NOT NULL,
    link TEXT NOT NULL, -- Closest link to the paper, chapter, or section
    updated_at TIMESTAMPTZ NOT NULL, -- Last time this paper's info was updated
    abstract TEXT,
    journal_ref TEXT,
    categories TEXT[],
    citations INT, -- NULL if unknown
    in_validation BOOLEAN,

    PRIMARY KEY(id, source)
);

COMMENT ON TABLE paper IS
'Stores paper metadata. A paper groups related theorems for citation.';

CREATE INDEX idx_paper_title_trgm ON paper USING GIN (LOWER(title) gin_trgm_ops);