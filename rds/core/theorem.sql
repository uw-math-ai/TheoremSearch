CREATE TABLE theorem (
    theorem_id BIGSERIAL PRIMARY KEY,
    paper_id TEXT NOT NULL REFERENCES paper(paper_id) ON DELETE CASCADE,
    name TEXT NOT NULL, -- Format if applicable: <type, capitalized> <ref> (<note>)
    body TEXT NOT NULL, -- Raw LaTeX theorem body with macros expanded
    label TEXT, -- Reference label of a theorem within a paper
    link TEXT, -- Closest link to the theorem. If the same as paper.link, keep NULL
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE theorem IS
'Stores theorem metadata. A theorem is a mathematical statement.';