-- Backfill the Lean signatures that were ingested as empty strings.
--
-- APPLIED 2026-09-27: 179,335 rows updated in 120s. Formal statements with a
-- signature went from 205,454 to 384,789 of 388,105 (99.1%).
--
-- Why they were empty: corpus_v3/ingestion/ingest.py reads `signature` from a
-- separate <project>_statements.jsonl export and defaults it to '' when that
-- file is absent, so projects ingested without their statements export
-- (Mathlib_v427 52% empty, PrimeNumberTheoremAnd 50%) got empty signatures,
-- while physlib / carleson / sphere-packing-math-inc have theirs. The gap lines
-- up exactly with the abbreviated kinds that path wrote ('thm' 142,696,
-- 'def' 20,281, 'inst' 17,018 — all 100% empty) versus the full words
-- ('theorem', 'definition', 'instance' — none empty).
--
-- The corrected signatures were already staged in statement_body_backfill
-- (179,335 rows, src = 'corpus_v3_corrected', 2026-06-11) but never applied.
-- Before applying: 179,288 of 179,335 bodies (100.0%) started with their own
-- declaration name, and no row targeted a statement that already had a body.
--
-- statement_search does not store bodies, so nothing needed rebuilding.

UPDATE statement st
   SET body = b.body
  FROM statement_body_backfill b
 WHERE st.statement_id = b.statement_id
   AND st.formality = 'formal'
   AND st.body = ''            -- never overwrite a signature we already have
   AND length(b.body) > 0;

-- Verify:
--   SELECT count(*) FILTER (WHERE body <> '') AS with_signature,
--          count(*) FILTER (WHERE body = '')  AS still_empty
--     FROM statement WHERE formality = 'formal';
--
-- Roll back (the prior value was uniformly the empty string):
--   UPDATE statement st SET body = ''
--     FROM statement_body_backfill b
--    WHERE st.statement_id = b.statement_id AND st.body = b.body;
--
-- Still outstanding: 3,316 formal statements have no backfill row and remain
-- empty. Those need a fresh lean-graph export — corpus_v3.db and the
-- *_statements.jsonl files are not in this repo, not in S3
-- (math-graph-bucket/statement_formal.csv was dumped from v2 and carries the
-- same empty bodies), so presumably they live on an EC2 box or a workstation.
--
-- Not done, and optional: the slogans for these statements were generated
-- while the signature was empty, from the declaration name plus dependency
-- context. They read accurately in spot checks and only 1,411 of 182,651 are
-- flagged insufficient_context, so this was a display problem rather than a
-- retrieval one. Regenerating them (and their embeddings) with the signatures
-- present would still be an improvement:
--   python -m pipeline.generate_slogans --formal -m qwen3-235b --overwrite \
--       -c "statement.formality = 'formal' AND statement.body <> ''"
