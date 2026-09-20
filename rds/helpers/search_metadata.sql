-- Filter-panel metadata for theoremsearch.com (theorem-search-app
-- app/api/metadata/route.ts). v2 replacements for the v1 mv_sources,
-- mv_authors_by_source, mv_tags_by_source and mv_theorem_count views, which
-- read theorem_search_qwen8b in the `postgres` database.
--
-- "Searchable" = what /graph/embedding can return: a row of statement_search
-- (a statement with a sufficient-context qwen3-235b slogan embedded by
-- qwen3-8b). Build statement_search first (rds/scripts/build_statement_search.py).
--
-- Apply with:   psql -d v2 -f rds/helpers/search_metadata.sql
-- Refresh after ingestion (each takes minutes; CONCURRENTLY keeps them
-- readable while refreshing):
--   REFRESH MATERIALIZED VIEW CONCURRENTLY mv_search_source_stats;
--   REFRESH MATERIALIZED VIEW CONCURRENTLY mv_search_authors_by_source;
--   REFRESH MATERIALIZED VIEW CONCURRENTLY mv_search_tags_by_source;

-- Per source: searchable statement counts and the ranges the year/citation
-- filters need. statement_search already holds exactly the searchable rows
-- (one per embedding) with these columns, so this reads that instead of
-- re-joining embedding/slogan/statement/paper.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_search_source_stats AS
SELECT
    source,
    count(DISTINCT statement_id) FILTER (WHERE formality = 'informal') AS informal_statements,
    count(DISTINCT statement_id) FILTER (WHERE formality = 'formal')   AS formal_statements,
    min(year)                                                          AS year_min,
    max(year)                                                          AS year_max,
    max(citation_count)                                                AS citation_max
FROM statement_search
GROUP BY source;

CREATE UNIQUE INDEX IF NOT EXISTS mv_search_source_stats_source
    ON mv_search_source_stats (source);

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_search_authors_by_source AS
SELECT p.source, array_agg(DISTINCT a.author ORDER BY a.author) AS authors
FROM paper p
CROSS JOIN LATERAL unnest(p.authors) AS a(author)
WHERE p.source IS NOT NULL
  AND EXISTS (SELECT 1 FROM statement_search ss WHERE ss.paper_id = p.paper_id)
GROUP BY p.source;

CREATE UNIQUE INDEX IF NOT EXISTS mv_search_authors_by_source_source
    ON mv_search_authors_by_source (source);

-- Primary category only (categories[1]), matching the /graph/embedding filter.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_search_tags_by_source AS
SELECT p.source, array_agg(DISTINCT p.categories[1] ORDER BY p.categories[1]) AS tags
FROM paper p
WHERE p.source IS NOT NULL
  AND cardinality(p.categories) > 0
  AND EXISTS (SELECT 1 FROM statement_search ss WHERE ss.paper_id = p.paper_id)
GROUP BY p.source;

CREATE UNIQUE INDEX IF NOT EXISTS mv_search_tags_by_source_source
    ON mv_search_tags_by_source (source);
