-- Indexes to support parse_dependencies pipeline performance.
-- Apply with: psql -d v2 -f rds/core/indexes.sql

-- 1. statement(paper_id)
--    Highest ROI. Used in EXISTS/NOT EXISTS outer scans, batch statement
--    fetches, and interpaper dep lookups — hit on every paper processed.
CREATE INDEX IF NOT EXISTS idx_statement_paper_id
    ON statement(paper_id);

-- 2. dependency(source_id, interpaper)
--    Covers NOT EXISTS skip-check (both intra and inter variants) and the
--    DELETE before each batch write. No index existed on source_id at all.
CREATE INDEX IF NOT EXISTS idx_dependency_source_interpaper
    ON dependency(source_id, interpaper);

-- 3. paper(kind, external_id)
--    The existing UNIQUE(source, external_id) doesn't help for the common
--    WHERE kind = 'paper' AND external_id = %s pattern used in interpaper
--    step 1 (exact arXiv match) and statement fetches.
CREATE INDEX IF NOT EXISTS idx_paper_kind_external_id
    ON paper(kind, external_id);

-- 4. GIN trigram index on LOWER(paper.title)
--    Required for Stage 2 title-match in interpaper. Without this, the
--    LATERAL loop does a seq scan per unresolved bib entry. Requires pg_trgm.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS idx_paper_title_trgm
    ON paper USING gin(LOWER(title) gin_trgm_ops);

-- 5. informal_metadata(ref)
--    Interpaper step 3 dep lookup: WHERE im.ref = q.ref.
CREATE INDEX IF NOT EXISTS idx_informal_metadata_ref
    ON informal_metadata(ref);
