CREATE TABLE paper (
    paper_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    authors TEXT[] NOT NULL,
    link TEXT NOT NULL,
    last_updated TIMESTAMPTZ,
    summary TEXT,
    journal_ref TEXT,
    primary_category TEXT,
    categories TEXT[],
    citations INT
);

CREATE TABLE paper_arxiv_s3_location (
    paper_id TEXT PRIMARY KEY NOT NULL REFERENCES paper(paper_id) ON DELETE CASCADE,
    bundle_tar TEXT NOT NULL,
    bytes_start INT NOT NULL,
    bytes_end INT NOT NULL
)

CREATE TABLE theorem (
    theorem_id BIGSERIAL PRIMARY KEY,
    paper_id TEXT NOT NULL REFERENCES paper(paper_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    body TEXT NOT NULL,
    label TEXT,
    link TEXT,

    UNIQUE (paper_id, name)
);

CREATE TABLE theorem_slogan (
    slogan_id BIGSERIAL PRIMARY KEY,
    theorem_id BIGINT NOT NULL REFERENCES theorem(theorem_id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    prompt_id TEXT NOT NULL,
    slogan TEXT NOT NULL,

    UNIQUE (theorem_id, model, prompt_id)
);

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE theorem_embedding_bert (
    slogan_id BIGINT PRIMARY KEY REFERENCES theorem_slogan(slogan_id) ON DELETE CASCADE,
    embedding vector(768) NOT NULL
);

CREATE TABLE theorem_embedding_qwen (
    slogan_id BIGINT PRIMARY KEY REFERENCES theorem_slogan(slogan_id) ON DELETE CASCADE,
    embedding vector(1024) NOT NULL
);