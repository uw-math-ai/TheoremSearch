CREATE TABLE theorem (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id TEXT NOT NULL,
    source TEXT NOT NULL,
    type TEXT NOT NULL,
    ref TEXT,
    note TEXT,
    body TEXT NOT NULL, -- Raw LaTeX theorem body with macros expanded
    proof TEXT, -- Raw LaTeX theorem proof with macros expanded
    label TEXT, -- Reference label of a theorem within a paper
    link TEXT, -- Closest link to the theorem. If the same as paper.link, keep NULL
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    theorem_dependencies TEXT[],

    FOREIGN KEY (paper_id, source) REFERENCES paper (id, source)
    ON DELETE CASCADE
);

COMMENT ON TABLE theorem IS
'Stores theorem metadata. A theorem is a mathematical statement.';