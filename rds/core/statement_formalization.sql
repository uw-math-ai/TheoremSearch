-- A claim that an informal statement (e.g. LaTeX blueprint) is formalized by
-- a particular formal statement (e.g. Lean decl). Many-to-many: a blueprint
-- statement with `\lean{a, b, c}` produces three rows; a Lean decl restated
-- in two different informal paragraphs produces two rows.
--
-- ``methods`` accumulates every signal that surfaced the link, mirroring
-- ``informal_dependency.methods``. Method-specific details (similarity
-- scores, model versions, blueprint label of origin, …) live in ``evidence``
-- as a JSONB blob keyed by method name. Example:
--
--   {
--     "blueprint": {"label": "mzi", "chapter": "ap"},
--     "embedding": {"similarity": 0.87, "model": "BAAI/bge-large-en-v1.5"},
--     "llm":       {"confidence": 0.92, "model_alias": "qwen3-235b"}
--   }
--
-- This is the authoritative table for the FL↔NL correspondence; the older
-- ``statement_link`` relation ``'fl_nl_match'`` is now superseded for this
-- specific use case but remains valid for the other (informal↔informal)
-- relations it tracks.
CREATE TABLE statement_formalization (
    informal_statement_id UUID NOT NULL REFERENCES statement(statement_id) ON DELETE CASCADE,
    formal_statement_id   UUID NOT NULL REFERENCES statement(statement_id) ON DELETE CASCADE,
    methods TEXT[] NOT NULL DEFAULT '{}'
                CHECK (methods <@ ARRAY[
                    'blueprint',  -- \lean{decl_name} tag in blueprint LaTeX
                    'embedding',  -- vector similarity above threshold
                    'llm',        -- online LLM asserted the correspondence
                    'judge',      -- LLM judge confirmed an embedding/llm candidate
                    'manual'      -- human-curated
                ]::text[]),
    evidence    JSONB,
    note        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (informal_statement_id, formal_statement_id)
);

COMMENT ON TABLE statement_formalization IS
'Asserts that one informal statement is formalized as one formal statement. methods records every signal that pointed to the link; evidence carries method-specific details (similarity scores, model versions, blueprint label of origin, …).';

CREATE INDEX statement_formalization_formal_idx
    ON statement_formalization (formal_statement_id);
