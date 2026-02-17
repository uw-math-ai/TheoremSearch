CREATE TABLE s3_location (
    arxiv_id TEXT NOT NULL,
    source TEXT NOT NULL,
    bundle_key TEXT NOT NULL,
    bytes_range TEXT NOT NULL,

    PRIMARY KEY (arxiv_id, source),

    FOREIGN KEY (arxiv_id, source)
    REFERENCES paper (id, source)
    ON DELETE CASCADE
);

COMMENT ON TABLE s3_location IS
'Index of locations of an arXiv LaTeX source in the S3 bucket "arxiv".';
