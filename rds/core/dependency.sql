-- Directed informal dependency: src_id depends on dep_id (or on a paper via cite_id).
--
-- Intrapaper (\ref):            cite_id = NULL,  cite_key = NULL,  dep_key = \label value
-- Interpaper resolved (\cite):  cite_id = paper UUID, cite_key = \cite key, dep_key = ref within cite if known
-- Interpaper unresolved (\cite): cite_id = NULL, cite_key = \cite key, dep_key = ref within cite if known
--
-- cite_key IS NULL  ↔  intrapaper
-- cite_key IS NOT NULL ↔  interpaper (resolved or not)
--
-- dep_id is filled whenever the target statement was resolved; dep_name is filled for
-- interpaper deps only, and only when the cite explicitly names a target (e.g. "Theorem A.1").
CREATE TABLE informal_dependency (
    src_id      UUID NOT NULL REFERENCES statement(statement_id) ON DELETE CASCADE,
    location    TEXT NOT NULL CHECK (location IN ('body', 'note', 'proof', 'pre_context', 'post_context')),
    cite_id     UUID REFERENCES paper(paper_id) ON DELETE CASCADE,  -- NULL for intrapaper
    cite_key    TEXT,       -- \cite key; NULL for intrapaper
    dep_id      UUID REFERENCES statement(statement_id) ON DELETE SET NULL,
    dep_key     TEXT,       -- \label (deterministic intrapaper) or implied phrase (LLM-only deps of either kind); NULL otherwise
    dep_name    TEXT,       -- human-readable target name, e.g. "Theorem 3.2"
    methods     TEXT[] NOT NULL DEFAULT '{}'
                    CHECK (methods <@ ARRAY['deterministic','heuristic','llm','judge']::text[])
);

COMMENT ON TABLE informal_dependency IS
'A directed dependency edge from an informal statement to another statement or paper.';

-- Formal dependencies (e.g. extracted from Lean via lean-graph).
--
-- edge_type mirrors lean-graph's emitted kinds; the PK includes it because a
-- single (src, dep) pair can legitimately appear under multiple kinds (e.g.
-- a decl used in both a signature and its own proof).
CREATE TABLE formal_dependency (
    src_id          UUID NOT NULL REFERENCES statement(statement_id) ON DELETE CASCADE,
    dep_id          UUID NOT NULL REFERENCES statement(statement_id) ON DELETE CASCADE,
    edge_type       TEXT NOT NULL CHECK (edge_type IN (
                        'extends',  -- structure/class extends
                        'field',    -- structure field reference
                        'sig',      -- used in the declaration's signature/type
                        'proof',    -- used in the proof term/body
                        'def',      -- used in the value of a definition
                        'docref'    -- referenced from docstring
                    )),
    tactic_context  TEXT,   -- optional: tactic or term excerpt that triggered this dependency
    -- lean-graph sig-edge metadata (NULL for non-sig edges)
    position        TEXT CHECK (position IS NULL OR position IN ('conclusion', 'hyp')),
    binder          TEXT CHECK (binder   IS NULL OR binder   IN ('explicit', 'inst', 'implicit', 'strict')),
    role            TEXT CHECK (role     IS NULL OR role     IN ('fn', 'arg')),
    via_proj        BOOLEAN,
    PRIMARY KEY (src_id, dep_id, edge_type)
);

COMMENT ON TABLE formal_dependency IS
'A directed dependency edge between two formal (e.g. Lean) statements. edge_type matches the lean-graph emitter''s vocabulary.';
