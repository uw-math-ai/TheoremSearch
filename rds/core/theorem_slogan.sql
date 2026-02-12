CREATE TABLE theorem_slogan (
    slogan_id BIGSERIAL PRIMARY KEY,
    theorem_id BIGINT NOT NULL REFERENCES theorem(theorem_id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    prompt_id TEXT NOT NULL,
    slogan TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()

    UNIQUE (theorem_id, model, prompt_id)
);

COMMENT ON TABLE theorem_slogan IS
'Stores theorem slogans. A theorem slogan is a plain-English summary of a theorem given context.';