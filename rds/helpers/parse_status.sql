CREATE TABLE parse_status (
    paper_id TEXT NOT NULL,
    source TEXT NOT NULL,
    last_parse_attempt_at TIMESTAMPTZ NOT NULL, -- Last time this paper had a parse attempt
    error TEXT,
    s3 BOOLEAN DEFAULT FALSE,
    parsing_method TEXT NOT NULL,
    validation_level TEXT NOT NULL,

    PRIMARY KEY (arxiv_id, source),

    FOREIGN KEY (paper_id, source) REFERENCES paper (id, source)
    ON DELETE CASCADE
);

COMMENT ON TABLE parse_status IS
'Stores status of parsed papers.';
