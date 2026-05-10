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

-- 12. statement(statement_id) INCLUDE (paper_id)
--     Covering index for the dep-count aggregation query: after scanning
--     informal_dependency by src_id, the join to statement needs paper_id.
--     Without this, Postgres does a heap fetch per row; with it, the join
--     is an index-only scan.
CREATE INDEX IF NOT EXISTS idx_statement_id_covering_paper
    ON statement(statement_id) INCLUDE (paper_id);

-- 13. informal_dependency(src_id) partial — judge intrapaper deps only
--     Targets the common "filter to papers with judge deps" pattern used by
--     experiments and by re-running parsers conditioned on judge output.
--     Without this, the EXISTS subquery does a GIN scan + statement join
--     per outer paper; with it, each EXISTS is a single index seek.
CREATE INDEX IF NOT EXISTS idx_informal_dependency_judge_src
    ON informal_dependency(src_id)
    WHERE cite_key IS NULL AND 'judge' = ANY(methods);

-- 14. paper(external_id)
--     Required for the arxiv_paper_metadata.arxiv_id = paper.external_id join
--     used by the slogan batch-prepare query (and any -c "apm.<col>" filter).
--     The existing (source, external_id) and (kind, external_id) composite
--     indexes can't satisfy a lookup keyed only on external_id.
CREATE INDEX IF NOT EXISTS idx_paper_external_id
    ON paper(external_id);

-- 15. arxiv_paper_metadata(arxiv_id) partial — validation papers only
--     Lets `-c "apm.in_validation"` filters seek directly to the small set
--     of validation papers instead of scanning all of arxiv_paper_metadata.
CREATE INDEX IF NOT EXISTS idx_arxiv_paper_metadata_in_validation
    ON arxiv_paper_metadata(arxiv_id)
    WHERE in_validation;

-- 16. informal_dependency(src_id) partial — LLM intrapaper deps the judge
--     rejected. Supports the analysis query that filters
--     `'llm' = ANY(methods) AND NOT ('judge' = ANY(methods))`, which
--     neither the GIN on methods nor the existing partial indexes cover.
CREATE INDEX IF NOT EXISTS idx_informal_dependency_llm_not_judge
    ON informal_dependency(src_id)
    WHERE cite_key IS NULL
      AND 'llm' = ANY(methods)
      AND NOT ('judge' = ANY(methods));

-- 17. statement(kind)
--     Filter statements by lean-graph DeclarationType (thm/def/ind/...).
CREATE INDEX IF NOT EXISTS idx_statement_kind
    ON statement(kind);

-- 18. formal_metadata(decl_name) and formal_metadata(module)
--     decl_name: lookup by Lean FQN (the join key from lean-graph nodes).
--     module: filter formal statements by defining Lean module.
CREATE INDEX IF NOT EXISTS idx_formal_metadata_decl_name
    ON formal_metadata(decl_name);
CREATE INDEX IF NOT EXISTS idx_formal_metadata_module
    ON formal_metadata(module);

-- 19. statement_link reverse-lookup index
--     The PK (a_id, b_id, relation) covers a_id-keyed lookups; this covers
--     the b_id side so "all links touching X" can be found from either end.
CREATE INDEX IF NOT EXISTS idx_statement_link_b
    ON statement_link(b_id, relation);
CREATE INDEX IF NOT EXISTS idx_statement_link_relation
    ON statement_link(relation);
