CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE embedding_model (
    name        TEXT PRIMARY KEY,
    model       TEXT NOT NULL,
    instruction TEXT,
    dim         INT NOT NULL,
    normalized  BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE embedding_model IS
'Registered embedding model configs. The name is its own ID; rename the entry to evolve.';

CREATE TABLE embedding (
    embedding_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slogan_id    UUID NOT NULL REFERENCES slogan(slogan_id) ON DELETE CASCADE,
    model_name   TEXT NOT NULL REFERENCES embedding_model(name),
    embedding    vector NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (slogan_id, model_name)
);

COMMENT ON TABLE embedding IS
'One embedding per (slogan, embedding-model). Source text is slogan.slogan, encoded with the model''s registered instruction. Overwriting preserves the original created_at.';
