import os
import json
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import List, Optional
from openai import OpenAI
from contextlib import contextmanager
from psycopg2.pool import SimpleConnectionPool
from pgvector.psycopg2 import register_vector
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# Initialize OpenAI client
client = OpenAI(
    base_url="https://api.tokenfactory.nebius.com/v1/",
    api_key=os.environ["NEBIUS_API_KEY"]
)

# Database connection setup
_reader_pool = SimpleConnectionPool(
    1, 10,
    host=os.getenv("RDS_DB_HOST"),
    port=int(os.getenv("RDS_DB_PORT", "5432")),
    dbname=os.getenv("RDS_DB_NAME"),
    user=os.getenv("RDS_DB_USER"),
    password=os.getenv("RDS_DB_PASSWORD"),
    sslmode="require",
)

@contextmanager
def reader_conn():
    """Get a connection from the reader pool"""
    conn = _reader_pool.getconn()
    try:
        register_vector(conn)
        yield conn
    finally:
        _reader_pool.putconn(conn)

_writer_pool = SimpleConnectionPool(
    1, 5,
    host=os.getenv("RDS_DB_HOST"),
    port=int(os.getenv("RDS_DB_PORT", "5432")),
    dbname=os.getenv("RDS_DB_NAME"),
    user=os.getenv("RDS_DB_USER"),
    password=os.getenv("RDS_DB_PASSWORD"),
    sslmode="require",
)

@contextmanager
def writer_conn():
    conn = _writer_pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _writer_pool.putconn(conn)

# Pydantic Models
class SearchRequest(BaseModel):
    query: str
    n_results: int = 10
    sources: List[str] = []
    authors: List[str] = []
    types: List[str] = []
    tags: List[str] = []
    paper_filter: Optional[str] = None
    year_range: Optional[List[int]] = None
    citation_range: Optional[List[int]] = None
    citation_weight: float = 0.0
    include_unknown_citations: bool = True

class PaperResult(BaseModel):
    paper_id: str
    source: str
    title: str
    authors: List[str]
    link: str
    summary: Optional[str] = None
    journal_ref: Optional[str] = None
    primary_category: Optional[str] = None
    categories: List[str] = []
    citations: Optional[int] = None
    year: Optional[int] = None
    journal_published: Optional[bool] = None

class TheoremResult(BaseModel):
    slogan_id: int
    theorem_id: int
    name: str
    body: str
    slogan: str
    theorem_type: str
    label: Optional[str] = None
    link: Optional[str] = None
    paper: PaperResult
    similarity: float
    score: float
    has_metadata: bool

class SearchResponse(BaseModel):
    theorems: List[TheoremResult]


MCP_SEARCH_TOOL = {
    "name": "theorem_search",
    "description": "Search for mathematical theorems using semantic similarity and filters.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "n_results": {"type": "integer", "default": 10},
            "sources": {"type": "array", "items": {"type": "string"}, "default": []},
            "authors": {"type": "array", "items": {"type": "string"}, "default": []},
            "types": {"type": "array", "items": {"type": "string"}, "default": []},
            "tags": {"type": "array", "items": {"type": "string"}, "default": []},
            "paper_filter": {"type": ["string", "null"], "default": None},
            "year_range": {"type": ["array", "null"], "items": {"type": "integer"}, "default": None},
            "citation_range": {"type": ["array", "null"], "items": {"type": "integer"}, "default": None},
            "citation_weight": {"type": "number", "default": 0.0},
            "include_unknown_citations": {"type": "boolean", "default": True},
        },
        "required": ["query"],
    },
}

# Helper functions
def embed_query(query: str) -> List[float]:
    """Generate embedding for search query"""
    response = client.embeddings.create(
        model="Qwen/Qwen3-Embedding-8B",
        input=query,
        encoding_format="float"
    )
    return response.data[0].embedding

def row_to_dict(cursor, row):
    """Convert database row to dictionary"""
    return {desc[0]: row[i] for i, desc in enumerate(cursor.description)}

def fetch_candidate_ids(
    query_vec: List[float],
    citation_weight: float,
    top_k: int,
    selected_sources: List[str],
) -> List[tuple]:
    """Fetch candidate theorem IDs using ANN search per source"""
    
    if not selected_sources:
        return []

    # Tune these parameters
    per_source_multiplier = 3
    ef_search = max(80, top_k * 4)

    with reader_conn() as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL hnsw.ef_search = %s;", (ef_search,))
        cur.execute("SET LOCAL hnsw.iterative_scan = 'relaxed_order';")

        all_rows = []

        for source in selected_sources:
            sql = """
            WITH ann AS (
                SELECT
                    slogan_id,
                    citations,
                    embedding
                FROM theorem_search_qwen8b
                WHERE source = %(source)s
                ORDER BY
                    (binary_quantize(embedding)::bit(4096))
                    <~>
                    binary_quantize(%(query_vec_ann)s::vector(4096))::bit(4096)
                LIMIT %(per_source_limit)s
            )
            SELECT
                slogan_id,
                (1.0 - (embedding <=> %(query_vec_rerank)s::vector(4096))) AS similarity,
                (1.0 - (embedding <=> %(query_vec_rerank)s::vector(4096)))
                + %(citation_weight)s * CASE
                    WHEN citations > 0 THEN ln(citations::float)
                    ELSE 0
                  END AS score
            FROM ann;
            """

            params = {
                "source": source,
                "query_vec_ann": query_vec,
                "query_vec_rerank": query_vec,
                "citation_weight": citation_weight,
                "per_source_limit": top_k * per_source_multiplier,
            }

            cur.execute(sql, params)
            all_rows.extend(cur.fetchall())

        if not all_rows:
            return []

        # Global rerank across sources
        all_rows.sort(key=lambda x: x[2], reverse=True)

        return all_rows[:top_k]

def fetch_full_rows(slogan_rows: List[tuple]) -> List[dict]:
    """Fetch complete theorem and paper data for candidate IDs"""
    
    if not slogan_rows:
        return []

    slogan_ids = [r[0] for r in slogan_rows]
    score_map = {r[0]: (r[1], r[2]) for r in slogan_rows}

    with reader_conn() as conn, conn.cursor() as cur:
        sql = """
        SELECT
            slogan_id,
            theorem_id,
            paper_id,
            theorem_name,
            theorem_body,
            theorem_slogan,
            theorem_type,
            title,
            authors,
            link,
            year,
            journal_published,
            primary_category,
            categories,
            citations,
            source,
            has_metadata
        FROM theorem_search_qwen8b
        WHERE slogan_id = ANY(%(ids)s)
        ORDER BY array_position(%(ids)s, slogan_id);
        """

        cur.execute(sql, {"ids": slogan_ids})
        rows = cur.fetchall()

    return [
        {
            **row_to_dict(cur, row),
            "similarity": score_map[row[0]][0],
            "score": score_map[row[0]][1],
        }
        for row in rows
    ]

def apply_filters(
    results: List[dict],
    authors: List[str],
    types: List[str],
    tags: List[str],
    paper_filter: Optional[str],
    year_range: Optional[List[int]],
    citation_range: Optional[List[int]],
    include_unknown_citations: bool,
) -> List[dict]:
    """Apply post-search filters to results"""
    
    filtered = results

    # Filter by authors
    if authors:
        authors_lower = [a.lower() for a in authors]
        filtered = [
            r for r in filtered
            if r.get('authors') and any(
                any(author_filter in author.lower() for author_filter in authors_lower)
                for author in r['authors']
            )
        ]

    # Filter by theorem type
    if types:
        types_lower = [t.lower() for t in types]
        filtered = [
            r for r in filtered
            if r.get('theorem_type') and r['theorem_type'].lower() in types_lower
        ]

    # Filter by tags (primary_category)
    if tags:
        tags_lower = [t.lower() for t in tags]
        filtered = [
            r for r in filtered
            if r.get('primary_category') and r['primary_category'].lower() in tags_lower
        ]

    # Filter by paper (search in title)
    if paper_filter:
        paper_filter_lower = paper_filter.lower()
        filtered = [
            r for r in filtered
            if r.get('title') and paper_filter_lower in r['title'].lower()
        ]

    # Filter by year range
    if year_range and len(year_range) == 2:
        min_year, max_year = year_range
        filtered = [
            r for r in filtered
            if r.get('year') is not None and min_year <= r['year'] <= max_year
        ]

    # Filter by citation range
    if citation_range and len(citation_range) == 2:
        min_citations, max_citations = citation_range
        filtered = [
            r for r in filtered
            if (r.get('citations') is not None and min_citations <= r['citations'] <= max_citations) or
               (include_unknown_citations and r.get('citations') is None)
        ]

    return filtered

@app.get("/")
async def root():
    return {"message": "TheoremSearch API", "version": "1.0.0"}

@app.post("/search", response_model=SearchResponse)
async def search(payload: SearchRequest, mcp=False):
    """
    Search for theorems using semantic similarity and optional filters.
    
    Parameters:
    - query: Search query text
    - n_results: Number of results to return (default: 10)
    - sources: Filter by paper sources (e.g., ["arxiv", "mathlib"])
    - authors: Filter by author names
    - types: Filter by theorem types
    - tags: Filter by primary category
    - paper_filter: Filter by paper title (substring match)
    - year_range: Filter by publication year [min, max]
    - citation_range: Filter by citation count [min, max]
    - citation_weight: Weight for citation-based ranking (default: 0.0)
    - include_unknown_citations: Include papers with unknown citation counts (default: true)
    """
    
    try:
        with writer_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO api_search_query (
                    query_at, query, n_results, source, authors, types, tags,
                    paper_filter, year_range, citation_range, citation_weight,
                    include_unknown_citations, mcp
                ) VALUES (
                    NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    payload.query,
                    payload.n_results,
                    payload.sources or None,
                    payload.authors or None,
                    payload.types or None,
                    payload.tags or None,
                    payload.paper_filter,
                    payload.year_range or None,
                    payload.citation_range or None,
                    payload.citation_weight,
                    payload.include_unknown_citations,
                    mcp
                ),
            )

        # Generate query embedding
        query_vec = embed_query(payload.query)
        
        # Use all sources if none specified
        if not payload.sources:
            selected_sources = [
                "Stacks Project",
                "arXiv",
                "ProofWiki",
                "An Infinitely Large Napkin",
                "CRing Project",
                "HoTT Book",
                "Open Logic Project"
            ]
        else:
            selected_sources = payload.sources
        
        # Fetch candidates using ANN search
        candidates = fetch_candidate_ids(
            query_vec=query_vec,
            citation_weight=payload.citation_weight,
            top_k=payload.n_results * 2,  # Fetch more to allow for filtering
            selected_sources=selected_sources,
        )
        
        # Fetch full theorem and paper data
        results = fetch_full_rows(candidates)
        
        # Apply filters
        filtered_results = apply_filters(
            results=results,
            authors=payload.authors,
            types=payload.types,
            tags=payload.tags,
            paper_filter=payload.paper_filter,
            year_range=payload.year_range,
            citation_range=payload.citation_range,
            include_unknown_citations=payload.include_unknown_citations,
        )
        
        # Limit to requested number of results
        filtered_results = filtered_results[:payload.n_results]
        
        # Convert to response format
        theorems = []
        for result in filtered_results:
            paper = PaperResult(
                paper_id=result['paper_id'],
                source=result['source'],
                title=result['title'],
                authors=result['authors'] or [],
                link=result['link'],
                primary_category=result.get('primary_category'),
                categories=result.get('categories') or [],
                citations=result.get('citations'),
                year=result.get('year'),
                journal_published=result.get('journal_published'),
            )
            
            theorem = TheoremResult(
                slogan_id=result['slogan_id'],
                theorem_id=result['theorem_id'],
                name=result['theorem_name'],
                body=result['theorem_body'],
                slogan=result['theorem_slogan'],
                theorem_type=result['theorem_type'],
                paper=paper,
                similarity=result['similarity'],
                score=result['score'],
                has_metadata=result['has_metadata'],
            )
            
            theorems.append(theorem)
        
        return SearchResponse(theorems=theorems)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


def _mcp_success(request_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _mcp_error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


@app.api_route("/mcp", methods=["GET", "POST"])
async def mcp(request: Request):
    if request.method == "GET":
        return {
            "name": "TheoremSearch MCP",
            "version": "1.0.0",
            "endpoint": "/mcp",
            "methods": ["initialize", "tools/list", "tools/call"],
        }

    body = await request.json()
    request_id = body.get("id")
    method = body.get("method")

    if method == "initialize":
        return _mcp_success(
            request_id,
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "TheoremSearch MCP", "version": "1.0.0"},
            },
        )

    if method == "tools/list":
        return _mcp_success(request_id, {"tools": [MCP_SEARCH_TOOL]})

    if method == "tools/call":
        params = body.get("params") or {}
        if params.get("name") != MCP_SEARCH_TOOL["name"]:
            return _mcp_error(request_id, -32601, "Unknown tool")

        try:
            payload = SearchRequest(**(params.get("arguments") or {}))
            search_response = await search(payload, mcp=True)
        except Exception as e:
            return _mcp_error(request_id, -32603, str(e))

        response_payload = search_response.model_dump()
        return _mcp_success(
            request_id,
            {
                "content": [{"type": "text", "text": json.dumps(response_payload)}],
                "structuredContent": response_payload,
            },
        )

    return _mcp_error(request_id, -32601, f"Method not found: {method}")
