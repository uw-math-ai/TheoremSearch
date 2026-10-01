-- Denormalized search table behind /graph/embedding.
--
-- Why: in the normalized schema the vector (embedding) and the search filters
-- (paper.source, paper.categories, statement.formality, ...) live in
-- different tables. A filtered HNSW scan then has to join 4 tables per
-- candidate, and the planner can't estimate the filters' selectivity, so
-- filtered searches were slow and missed results in small slices (a single
-- Lean source, a rare arXiv category). v1 (theorem_search_qwen8b) avoided
-- this by keeping filter columns next to the vector with per-source partial
-- HNSW indexes; this table does the same for v2.
--
-- One row per searchable embedding: a qwen3-8b embedding of a
-- sufficient-context qwen3-235b slogan. Formal statements can have several
-- (one per slogan prompt); the API keeps the closest per statement.
--
-- Stores the binary-quantized vector only (512 bytes, stored inline) —
-- enough for the HNSW walk and for exact Hamming ranking of filtered subsets.
-- The full-precision rerank reads embedding.embedding via embedding_id for
-- the few hundred final candidates.
--
-- Populated and refreshed by rds/scripts/build_statement_search.py.

CREATE TABLE IF NOT EXISTS statement_search (
    -- Deleting a paper/statement/slogan cascades down to its embedding and
    -- from there to this row, so embedding_id is the only FK needed.
    embedding_id     UUID PRIMARY KEY REFERENCES embedding(embedding_id) ON DELETE CASCADE,
    statement_id     UUID NOT NULL,
    paper_id         UUID NOT NULL,
    source           TEXT NOT NULL,
    formality        formality_kind NOT NULL,
    kind             TEXT NOT NULL,        -- lower-case, Lean abbreviations expanded (thm -> theorem)
    primary_category TEXT,                 -- paper.categories[1]
    year             INT,                  -- year of paper.updated_at
    in_journal       BOOLEAN,              -- NULL when the source has no publication metadata
    citation_count   INT,                  -- NULL when unknown
    external_id      TEXT,                 -- lower-cased, for prefix matching
    bq               BIT(4096) NOT NULL    -- binary_quantize(embedding.embedding)
);

COMMENT ON TABLE statement_search IS
'Denormalized search rows for /graph/embedding: filter columns next to the binary-quantized embedding. Derived data; rebuild with rds/scripts/build_statement_search.py.';

-- Normalizes statement.kind for search (the formal ingesters disagree:
-- theorem/thm, definition/def, ...).
CREATE OR REPLACE FUNCTION search_kind(kind TEXT) RETURNS TEXT
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE lower(kind)
        WHEN 'thm'    THEN 'theorem'
        WHEN 'def'    THEN 'definition'
        WHEN 'inst'   THEN 'instance'
        WHEN 'struct' THEN 'structure'
        WHEN 'ctor'   THEN 'constructor'
        ELSE lower(kind)
    END
$$;

-- ---------------------------------------------------------------- indexes
-- Build AFTER the initial load (see build_statement_search.py --indexes).

-- ANN. arXiv is ~97% of rows; everything else (Lean sources, textbooks,
-- Stacks, ProofWiki, ...) gets its own small graph so filtering to those
-- sources never has to wade through arXiv candidates. Queries must repeat
-- the predicate verbatim for the planner to pick the partial index.
--   CREATE INDEX statement_search_bq_arxiv_hnsw ON statement_search
--       USING hnsw (bq bit_hamming_ops) WITH (m = 32, ef_construction = 256)
--       WHERE source = 'arXiv';
--   CREATE INDEX statement_search_bq_other_hnsw ON statement_search
--       USING hnsw (bq bit_hamming_ops) WITH (m = 32, ef_construction = 256)
--       WHERE source <> 'arXiv';

-- Filter-first plans: for restrictive filters the planner can collect the
-- matching rows by index and rank them by exact Hamming distance (512-byte
-- vectors make that cheap) instead of walking the HNSW graph.
--   CREATE INDEX statement_search_statement ON statement_search (statement_id);
--   CREATE INDEX statement_search_paper     ON statement_search (paper_id);
--   CREATE INDEX statement_search_category  ON statement_search (primary_category);
--   CREATE INDEX statement_search_year      ON statement_search (year);
--   CREATE INDEX statement_search_citations ON statement_search (citation_count);
--   CREATE INDEX statement_search_formal    ON statement_search (source) WHERE formality = 'formal';
--   CREATE INDEX statement_search_kind      ON statement_search (kind);
--   CREATE STATISTICS statement_search_source_formality (dependencies, mcv)
--       ON source, formality, kind FROM statement_search;
--
-- ADDED 2026-09-30. The filter-first plan above needs an index that can
-- *reach* the branch's rows, and `source <> 'arXiv'` is not indexable: only
-- the partial HNSW index carries that predicate, and it cannot be scanned as
-- a filter. So any search without a source filter split into an arXiv branch
-- (8.1M estimated rows -> HNSW walk) and a non-arXiv branch (66-85k rows ->
-- "exact Hamming"), and the exact branch seq-scanned all 12.5M rows / 8.1 GB
-- to find the 760k non-arXiv ones. That is the default shape the website
-- sends, and it measured 13-19s per search, warm or cold, never improving.
-- This partial index makes the branch an index scan instead: 1,042,441 pages
-- -> 4,124 (253x less I/O), plan 1.20s -> 0.10s, end-to-end 15.3s -> 0.34s.
-- Only 5 MB, because non-arXiv is 6% of the table.
--   CREATE INDEX CONCURRENTLY statement_search_other_filters
--       ON statement_search (formality, kind) WHERE source <> 'arXiv';
--
-- If a future filter on the non-arXiv branch still shows heap-fetch cost,
-- add INCLUDE (embedding_id, statement_id, bq) to make it index-only — that
-- grows the index to roughly 440 MB, so it was not worth it here.
