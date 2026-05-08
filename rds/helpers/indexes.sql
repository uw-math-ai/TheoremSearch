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

-- 6. dependency(dep_id)
--    Speeds up ON DELETE CASCADE from statement: without this, deleting a
--    statement does a seq scan on dependency for every dep_id match.
CREATE INDEX IF NOT EXISTS idx_dependency_dep_id
    ON dependency(dep_id);

-- 8. B-tree prefix index on lower(external_id)
--    Supports fast case-insensitive prefix search (arXiv IDs typed from start)
--    in the /paper-search endpoint. text_pattern_ops enables LIKE 'q%' plans.
CREATE INDEX IF NOT EXISTS idx_paper_external_id_lower_prefix
    ON paper (lower(external_id) text_pattern_ops);

-- 9. informal_dependency(src_id) partial — intrapaper deps only
--    Covers the dep-count subquery (--sample filter), Phase 2 dep fetch, and
--    both Phase 1 UPDATEs in the judge pipeline, all of which filter on
--    src_id with cite_key IS NULL AND dep_id IS NOT NULL.
CREATE INDEX IF NOT EXISTS idx_informal_dependency_src_intrapaper
    ON informal_dependency(src_id)
    WHERE cite_key IS NULL AND dep_id IS NOT NULL;

-- 10. GIN on informal_dependency(methods)
--     Required for any(methods) and && containment checks used by the judge
--     pipeline (skip-check, Phase 2 fetch, experiments query).
CREATE INDEX IF NOT EXISTS idx_informal_dependency_methods_gin
    ON informal_dependency USING gin(methods);

-- 11. informal_metadata(statement_id, ordinal)
--     Every paper's statement fetch joins on statement_id then sorts by ordinal.
--     The composite index lets Postgres satisfy both in one scan.
CREATE INDEX IF NOT EXISTS idx_informal_metadata_statement_ordinal
    ON informal_metadata(statement_id, ordinal);
