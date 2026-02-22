-- This currently only exists in database v1 (postgres) and NOT v2

CREATE TABLE api_search_query (
    query_at TIMESTAMPTZ NOT NULL,
    query TEXT,
    n_results INT,
    source TEXT[],
    authors TEXT[],
    types TEXT[],
    tags TEXT[],
    paper_filter TEXT,
    year_range INT[2],
    citation_range INT[2],
    citation_weight FLOAT,
    include_unknown_citations BOOLEAN,
    mcp BOOLEAN
);

COMMENT ON TABLE api_search_query IS
'User queries on the /search endpoint of the API';
