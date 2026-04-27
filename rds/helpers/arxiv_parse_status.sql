CREATE TABLE arxiv_parse_status (
    arxiv_id TEXT PRIMARY KEY TEXT,
    last_parse_attempt_at TIMESTAMPTZ NOT NULL, -- Last time this paper had a parse attempt
    error TEXT,
    parsing_method TEXT NOT NULL,
    validation_level TEXT NOT NULL
);

COMMENT ON TABLE arxiv_parse_status IS
'Stores status of parsed arXiv papers.';
