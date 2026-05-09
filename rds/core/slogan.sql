CREATE TABLE slogan_prompt (
    name       TEXT PRIMARY KEY,
    template   TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE slogan_prompt IS
'Registered prompt versions. The name is its own ID; rename the file to evolve.';

CREATE TABLE slogan_model (
    name        TEXT PRIMARY KEY,
    model       TEXT NOT NULL,
    temperature FLOAT,
    max_tokens  INT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE slogan_model IS
'Registered model configs. The name is its own ID; rename the entry to evolve.';

CREATE TABLE slogan (
    slogan_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    statement_id UUID NOT NULL REFERENCES statement(statement_id) ON DELETE CASCADE,
    prompt_name  TEXT NOT NULL REFERENCES slogan_prompt(name),
    model_name   TEXT NOT NULL REFERENCES slogan_model(name),
    slogan               TEXT NOT NULL,
    insufficient_context BOOLEAN NOT NULL,
    in_tokens            INT,
    out_tokens           INT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (statement_id, prompt_name, model_name)
);

COMMENT ON TABLE slogan IS
'One LLM-generated slogan per (statement, prompt, model). Overwriting preserves the original created_at.';
