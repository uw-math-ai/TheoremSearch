-- Preserve the 522 embeddings that existed only in theorem_embedding_qwen8b.
--
-- APPLIED 2026-10-01 against the `postgres` (v1) database. 522 rows, 9808 kB.
--
-- Why: theorem_embedding_qwen8b is 244 GB (1060 MB heap + 7.7 GB indexes +
-- ~235 GB TOAST for the 4096-d vectors) and is a candidate for dropping — it
-- has not been read since 2026-09-19, no production code or database object
-- references it, and theorem_search_qwen8b carries its own byte-identical copy
-- of the embeddings. "Byte-identical" was checked, not assumed: on a 1-in-4000
-- sample, 2,316 of 2,316 embeddings compared equal, 0 differing, 0 missing.
--
-- But the overlap is not total. A full anti-join found 522 slogan_ids present
-- only in theorem_embedding_qwen8b: 491 with prompt body-only-v1 and 31 with
-- body-and-abstract-v1, a prompt variant the denormalized search table never
-- carried. All 522 have non-empty slogans and live theorem rows. Those are
-- copied out here, with slogan text and theorem_id so the result stands on its
-- own, which makes dropping the big table lossless.

CREATE TABLE theorem_embedding_qwen8b_orphans AS
SELECT e.slogan_id,
       ts.theorem_id,
       ts.model,
       ts.prompt_id,
       ts.slogan,
       e.embedding
  FROM theorem_embedding_qwen8b e
  JOIN theorem_slogan ts ON ts.slogan_id = e.slogan_id
 WHERE NOT EXISTS (
           SELECT 1 FROM theorem_search_qwen8b s
            WHERE s.slogan_id = e.slogan_id
       );

ALTER TABLE theorem_embedding_qwen8b_orphans ADD PRIMARY KEY (slogan_id);

-- Verified after creation: 522 rows / 522 distinct slogan_id, matching the
-- source anti-join exactly; all 522 embeddings equal to their source row;
-- vector_dims uniformly 4096; no empty slogans; no null theorem_id.
--
-- These embeddings are recomputable if this table is ever lost: the slogan
-- text is in theorem_slogan and the model (Qwen3-Embedding-8B) is unchanged.
--
-- The source table was then dropped, on 2026-10-02:
--
--   DROP TABLE theorem_embedding_qwen8b;   -- 244 GB, took its 7.3 GB HNSW
--                                          -- and 355 MB pkey with it
--
-- A pre-flight re-ran the anti-join immediately before the drop and required
-- all three of: 522 rows unique to the source, 522 rows preserved here, and 0
-- preserved rows missing from the source. Afterwards the table was gone, this
-- table still held its 522 rows of 4096-d vectors, theorem_search_qwen8b was
-- intact (9,268,550 rows, all seven ANN indexes), and v1 /search, v2
-- /graph/embedding, /paper-search and the website's search path all still
-- answered.
--
-- Four non-production referents read the dropped table and will fail until
-- repointed at theorem_search_qwen8b. Each carries an in-file note saying so,
-- including the part that is easy to get wrong: theorem_search_qwen8b's HNSW
-- indexes are PARTIAL per source, while the dropped table's was the only
-- global one in v1, so an ANN query there must add WHERE source = 'arXiv'.
-- The files are experiments/final_test_revised.py,
-- experiments/evaluation/bm25_slogan_search.py, archive/prod/rds.py and
-- archive/prod/pca.ipynb.
--
-- Keep this table through any future v1 cleanup: the 31 body-and-abstract-v1
-- embeddings exist nowhere else, since theorem_search_qwen8b only ever
-- carried body-only-v1 slogans.
