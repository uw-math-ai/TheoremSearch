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
--       USING hnsw (bq bit_hamming_ops) WITH (m = 16, ef_construction = 256)
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
--
-- WHY m = 32 IS THE WRONG CHOICE HERE, 2026-09-30. A query vector that walks
-- an uncached region of the arXiv graph costs 5-10s end to end; the same
-- vector repeated costs 0.1-0.3s. The walk is bound by page reads, so its
-- cost scales with index size, and this index does not fit in Aurora's
-- ~8.75 GB of shared_buffers (which it also shares with the 8.1 GB heap).
--
-- v1 is the control. Its arXiv index was created with no reloptions, so it
-- took pgvector's defaults (m=16, ef_construction=64), and it quantized to
-- bit(4096) exactly as this one does:
--
--     v1  m=16  9,230,149 rows   829 B/row   7.12 GiB
--     v2  m=32 11,746,989 rows  1027 B/row  11.22 GiB
--
-- m=32 doubles the neighbor links (+24% B/row) and v2 carries 27% more rows,
-- so this index is 1.58x v1's. Walking both on the same cluster with the same
-- query vectors, ef_search=100, LIMIT 400, fresh vector per measurement:
-- v1 median 1.92s against v2 median 2.97s -- a 1.5x gap that tracks the 1.58x
-- size ratio. That is the whole reason v1 felt faster.
--
-- REBUILT AT m=16 ON 2026-10-01, and the DDL above now says so. The m=32
-- index was dropped and the new one renamed into its place on 2026-10-02, in
-- one transaction so the canonical name was never absent:
--
--   BEGIN;
--   DROP INDEX statement_search_bq_arxiv_hnsw;
--   ALTER INDEX statement_search_bq_arxiv_hnsw_m16
--       RENAME TO statement_search_bq_arxiv_hnsw;
--   COMMIT;
--
-- That took 0.1s and halved the index footprint on this table from 22 GB to
-- 11 GB. Afterwards the 21-case /graph/embedding smoke test passed against
-- production. No code references either index by name — only this file and
-- build_statement_search.py, and the rename keeps both correct. The sample
-- projection (832 B/row, ~9.1 GiB) held: the real index is 830 B/row and
-- 9298 MB, against 1025 B/row and 11.2 GiB for m=32. Build took 101 min with
-- maintenance_work_mem = 12GB and 4 parallel workers; pgvector spilled out of
-- memory at 10.7M of 11.7M tuples, so a larger setting would be faster still.
--
-- Verified on the full corpus at ef_search=100, not on a sample: the planner
-- prefers the m=16 index on cost, it walks in 1.69s median against 2.97s for
-- m=32, and recall@20 was **100% on all 8 test queries** measured against an
-- exact Hamming ranking over all 11,746,989 arXiv rows. The 1-point recall
-- gap seen on the 1.5M sample did not materialise at full scale, and
-- /graph/embedding reranks the survivors by full-precision cosine on top of
-- that.
--
-- Bigger lever, same direction: embedding_binary_hnsw_idx on the embedding
-- table is another 12.73 GiB built with the same m=32, so the two together
-- ask for 24 GiB of a 8.75 GiB cache and evict each other. Porting
-- /graph/statement's representations off it and dropping it would help search
-- residency more than the rebuild does.
--
-- Not an option: shrinking the stored vector (1024-bit quantization would
-- reach ~4-5 GiB) is ruled out — the 4096-bit quantization stays.
