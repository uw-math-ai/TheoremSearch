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
    method      TEXT NOT NULL DEFAULT 'deterministic'
                    CHECK (method IN ('deterministic', 'heuristic', 'llm', 'deterministic+llm', 'heuristic+llm'))
);

COMMENT ON TABLE informal_dependency IS
'A directed dependency edge from an informal statement to another statement or paper.';

-- Template for formal dependencies (e.g. extracted from Lean tactic traces).
-- Populate once a formal statement pipeline exists.
CREATE TABLE formal_dependency (
    src_id          UUID NOT NULL REFERENCES statement(statement_id) ON DELETE CASCADE,
    dep_id          UUID NOT NULL REFERENCES statement(statement_id) ON DELETE CASCADE,
    tactic_context  TEXT,   -- tactic or term that triggered this dependency
    PRIMARY KEY (src_id, dep_id)
);

COMMENT ON TABLE formal_dependency IS
'A directed dependency edge between two formal (e.g. Lean) statements.';
