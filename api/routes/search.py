import math
import os
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from openai import OpenAI

from db import rds_conn
from models import SearchRequest, SearchResponse, PaperResult, TheoremResult, DEFAULT_QUERY_PROMPT

router = APIRouter()

_openai_client: OpenAI = None

def get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(
            base_url="https://api.tokenfactory.nebius.com/v1/",
            api_key=os.environ["NEBIUS_API_KEY"],
        )
    return _openai_client


def embed_query(query: str, prompt: Optional[str] = None) -> List[float]:
    """Embed and L2-normalize. Corpus embeddings are stored normalized
    (embedding_model.normalized=TRUE for qwen3-8b); we keep the query side
    normalized too so any consumer that takes a raw dot product gets a
    true cosine."""
    text = (prompt + query) if prompt is not None else (DEFAULT_QUERY_PROMPT + query)
    response = get_openai_client().embeddings.create(
        model="Qwen/Qwen3-Embedding-8B",
        input=text,
        encoding_format="float",
    )
    vec = response.data[0].embedding
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm > 0 else vec


def row_to_dict(cursor, row):
    return {desc[0]: row[i] for i, desc in enumerate(cursor.description)}


def fetch_candidate_ids(
    query_vec: List[float],
    citation_weight: float,
    top_k: int,
    selected_sources: List[str],
) -> List[tuple]:
    if not selected_sources:
        return []

    per_source_multiplier = 3
    ef_search = max(80, top_k * 4)

    with rds_conn() as conn, conn.cursor() as cur:
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

        all_rows.sort(key=lambda x: x[2], reverse=True)
        return all_rows[:top_k]


def fetch_full_rows(slogan_rows: List[tuple]) -> List[dict]:
    if not slogan_rows:
        return []

    slogan_ids = [r[0] for r in slogan_rows]
    score_map = {r[0]: (r[1], r[2]) for r in slogan_rows}

    with rds_conn() as conn, conn.cursor() as cur:
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
    filtered = results

    if authors:
        authors_lower = [a.lower() for a in authors]
        filtered = [
            r for r in filtered
            if r.get("authors") and any(
                any(af in a.lower() for af in authors_lower)
                for a in r["authors"]
            )
        ]

    if types:
        types_lower = [t.lower() for t in types]
        filtered = [
            r for r in filtered
            if r.get("theorem_type") and r["theorem_type"].lower() in types_lower
        ]

    if tags:
        tags_lower = [t.lower() for t in tags]
        filtered = [
            r for r in filtered
            if r.get("primary_category") and r["primary_category"].lower() in tags_lower
        ]

    if paper_filter:
        pf_lower = paper_filter.lower()
        filtered = [
            r for r in filtered
            if r.get("title") and pf_lower in r["title"].lower()
        ]

    if year_range and len(year_range) == 2:
        min_year, max_year = year_range
        filtered = [
            r for r in filtered
            if r.get("year") is not None and min_year <= r["year"] <= max_year
        ]

    if citation_range and len(citation_range) == 2:
        min_c, max_c = citation_range
        filtered = [
            r for r in filtered
            if (r.get("citations") is not None and min_c <= r["citations"] <= max_c)
            or (include_unknown_citations and r.get("citations") is None)
        ]

    return filtered


@router.get("/")
async def root():
    return {"message": "TheoremSearch API", "version": "1.0.0"}


@router.post("/search", response_model=SearchResponse)
async def search(payload: SearchRequest, mcp: bool = False):
    try:
        with rds_conn() as conn, conn.cursor() as cur:
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
                    mcp,
                ),
            )

        query_vec = embed_query(payload.query, payload.prompt)

        selected_sources = payload.sources or [
            "Stacks Project",
            "arXiv",
            "ProofWiki",
            "An Infinitely Large Napkin",
            "CRing Project",
            "HoTT Book",
            "Open Logic Project",
        ]

        candidates = fetch_candidate_ids(
            query_vec=query_vec,
            citation_weight=payload.citation_weight,
            top_k=payload.db_top_k or payload.n_results * 2,
            selected_sources=selected_sources,
        )

        results = fetch_full_rows(candidates)

        filtered_results = apply_filters(
            results=results,
            authors=payload.authors,
            types=payload.types,
            tags=payload.tags,
            paper_filter=payload.paper_filter,
            year_range=payload.year_range,
            citation_range=payload.citation_range,
            include_unknown_citations=payload.include_unknown_citations,
        )[:payload.n_results]

        theorems = []
        for r in filtered_results:
            paper = PaperResult(
                paper_id=r["paper_id"],
                source=r["source"],
                title=r["title"],
                authors=r["authors"] or [],
                link=r["link"],
                primary_category=r.get("primary_category"),
                categories=r.get("categories") or [],
                citations=r.get("citations"),
                year=r.get("year"),
                journal_published=r.get("journal_published"),
            )
            theorems.append(TheoremResult(
                slogan_id=r["slogan_id"],
                theorem_id=r["theorem_id"],
                name=r["theorem_name"],
                body=r["theorem_body"],
                slogan=r["theorem_slogan"],
                theorem_type=r["theorem_type"],
                paper=paper,
                similarity=r["similarity"],
                score=r["score"],
                has_metadata=r["has_metadata"],
            ))

        return SearchResponse(theorems=theorems)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")
