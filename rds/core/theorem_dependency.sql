CREATE TABLE theorem_dependency (
    src_theorem_id UUID NOT NULL REFERENCES theorem(id) ON DELETE CASCADE,
    dep_key TEXT NOT NULL, -- either a theorem label or a paper BibTeX key
    interpaper BOOLEAN NOT NULL,
    dep_paper_id TEXT NULL,
    dep_paper_source TEXT NULL,
    dep_theorem_id UUID NULL REFERENCES theorem(id) ON DELETE CASCADE,
    
    FOREIGN KEY (dep_paper_id, dep_paper_source) REFERENCES paper (id, source)
    ON DELETE CASCADE,

    CONSTRAINT dep_paper_xor_theorem CHECK (
        -- Inter-paper, resolved to paper only
        (
            interpaper IS TRUE
            AND dep_paper_id IS NOT NULL
            AND dep_paper_source IS NOT NULL
            AND dep_theorem_id IS NULL
        )
        OR
        -- Inter-paper, resolved to specific theorem
        (
            interpaper IS TRUE
            AND dep_paper_id IS NULL
            AND dep_paper_source IS NULL
            AND dep_theorem_id IS NOT NULL
        )
        OR
        -- Intra-paper, always theorem-level
        (
            interpaper IS FALSE
            AND dep_paper_id IS NULL
            AND dep_paper_source IS NULL
            AND dep_theorem_id IS NOT NULL
        )
    ),

    PRIMARY KEY (src_theorem_id, dep_key)
);

COMMENT ON TABLE theorem_dependency IS
'Stores theorem dependencies: either a theorem dependency (preferred) or a paper dependency.';