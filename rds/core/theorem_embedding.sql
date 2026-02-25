CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE theorem_embedding (
    slogan_id BIGINT PRIMARY KEY REFERENCES theorem_slogan(id) ON DELETE CASCADE,
    embedding_model TEXT NOT NULL, -- Model name on Hugging Face
    embedding vector NOT NULL, -- Potentially different-length vectors! Requires indexing per model
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (slogan_id, embedding_model)
);

COMMENT ON TABLE theorem_embedding IS
'Stores theorem (slogan) embeddings.';

CREATE TABLE raw_theorem_embedding (
    theorem_id BIGINT PRIMARY KEY REFERENCES theorem(id) ON DELETE CASCADE,
    embedding_model TEXT NOT NULL, -- Model name on Hugging Face
    embedding vector NOT NULL, -- Potentially different-length vectors! Requires indexing per model
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (theorem_id, embedding_model)
);

COMMENT ON TABLE raw_theorem_embedding IS
'Stores (raw) theorem embeddings.';