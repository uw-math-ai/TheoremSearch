import os
from typing import List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query
from openai import OpenAI

from db import rds_conn
from models import (
    V2SearchResponse,
    V2SearchResult,
)

router = APIRouter()

EMBED_MODEL = "qwen3-8b"
QUERY_INSTRUCTION = "Given a math search query, retrieve theorems mathematically equivalent to the query.\n"

# Only slogans produced by these registered model aliases are eligible (matches
# slogan_model.name). Add new entries when you start generating slogans with a
# different model; the SQL filter follows automatically.
SLOGAN_MODELS = ["qwen3-235b"]

_openai_client: Optional[OpenAI] = None
_model_cache: dict[str, Tuple[str, Optional[str]]] = {}  # alias → (provider_model, doc-side instruction)


def _client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(
            base_url="https://api.studio.nebius.ai/v1/",
            api_key=os.environ["NEBIUS_API_KEY"],
        )
    return _openai_client


def _model_info(model_alias: str) -> Tuple[str, Optional[str]]:
    if model_alias not in _model_cache:
        with rds_conn("v2") as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT model, instruction FROM embedding_model WHERE name = %s",
                (model_alias,),
            )
            row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Unknown embedding model: {model_alias}")
        _model_cache[model_alias] = (row[0], row[1])
    return _model_cache[model_alias]


def _embed_query(query: str) -> List[float]:
    provider_model, _ = _model_info(EMBED_MODEL)
    resp = _client().embeddings.create(
        model=provider_model,
        input=QUERY_INSTRUCTION + query,
        encoding_format="float",
    )
    return resp.data[0].embedding


# Two-stage: HNSW on binary-quantized embeddings narrows the candidate pool by
# Hamming distance, then full-precision cosine reranks. Mirrors v1's pattern.
_SQL = """
WITH ann AS (
    SELECT e.slogan_id, e.embedding
    FROM embedding e
    JOIN slogan s ON s.slogan_id = e.slogan_id
    WHERE e.model_name = %(model)s
      AND s.model_name = ANY(%(slogan_models)s)
    ORDER BY
        binary_quantize(e.embedding)::bit(4096)
        <~>
        binary_quantize(%(q)s::vector(4096))::bit(4096)
    LIMIT %(ann_k)s
),
ranked AS (
    SELECT
        st.statement_id,
        p.paper_id,
        INITCAP(st.kind) || COALESCE(' ' || im.ref, '') AS name,
        st.body,
        s.slogan,
        p.source,
        p.title,
        p.authors,
        p.url,
        p.external_id,
        apm.citation_count,
        1.0 - (ann.embedding <=> %(q)s::vector(4096)) AS similarity
    FROM ann
    JOIN slogan s     ON s.slogan_id = ann.slogan_id
    JOIN statement st ON st.statement_id = s.statement_id
    JOIN paper p      ON p.paper_id = st.paper_id
    LEFT JOIN informal_metadata im     ON im.statement_id = st.statement_id
    LEFT JOIN arxiv_paper_metadata apm ON apm.arxiv_id = p.external_id
    WHERE NOT s.insufficient_context
      AND (%(sources)s::text[] IS NULL OR p.source = ANY(%(sources)s))
      AND (%(types)s::text[]   IS NULL OR LOWER(st.kind) = ANY(%(types)s))
      AND (%(author_patterns)s::text[] IS NULL OR EXISTS (
              SELECT 1 FROM unnest(p.authors) a
              WHERE LOWER(a) LIKE ANY(%(author_patterns)s)
      ))
      AND COALESCE(apm.citation_count, 0) >= %(min_citations)s
      AND (%(in_journal)s::boolean IS NULL
           OR (apm.journal_ref IS NOT NULL) = %(in_journal)s)
    ORDER BY ann.embedding <=> %(q)s::vector(4096)
    LIMIT %(top_k)s
)
SELECT *,
    similarity + %(cw)s * CASE
        WHEN COALESCE(citation_count, 0) > 0 THEN ln(COALESCE(citation_count, 0)::float)
        ELSE 0
    END AS score
FROM ranked
ORDER BY score DESC
LIMIT %(n)s;
"""


@router.get("/search", response_model=V2SearchResponse)
async def search(
    query: str = Query(..., min_length=1, description="Natural-language search query."),
    n_results: int = Query(10, ge=1, le=100),
    sources: List[str] = Query(default=[], description="Paper sources (repeat for multiple), e.g. 'arXiv', 'Stacks Project'."),
    types: List[str] = Query(default=[], description="Statement kinds to include (e.g. theorem, lemma)."),
    authors: List[str] = Query(default=[], description="Author substring filter (repeat for multiple)."),
    min_citations: int = Query(0, ge=0),
    citation_weight: float = Query(0.0, ge=0.0),
    in_journal: Optional[bool] = Query(None),
):
    try:
        query_vec = _embed_query(query)

        top_k = n_results * 5
        ann_k = max(top_k * 4, 200)

        params = {
            "q":               query_vec,
            "model":           EMBED_MODEL,
            "slogan_models":   SLOGAN_MODELS,
            "sources":         sources or None,
            "types":           [t.lower() for t in types] or None,
            "author_patterns": [f"%{a.lower()}%" for a in authors] or None,
            "min_citations":   min_citations,
            "in_journal":      in_journal,
            "cw":              citation_weight,
            "ann_k":           ann_k,
            "top_k":           top_k,
            "n":               n_results,
        }

        with rds_conn("v2") as conn, conn.cursor() as cur:
            cur.execute("SET LOCAL hnsw.ef_search = %s;", (max(ann_k, 200),))
            cur.execute("SET LOCAL hnsw.iterative_scan = 'relaxed_order';")
            cur.execute(_SQL, params)
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]

        return V2SearchResponse(results=[
            V2SearchResult(
                statement_id=str(r["statement_id"]),
                paper_id=str(r["paper_id"]),
                name=r["name"],
                body=r["body"],
                slogan=r["slogan"],
                source=r["source"],
                title=r["title"],
                authors=r["authors"] or [],
                url=r["url"],
                external_id=r["external_id"],
                citation_count=r["citation_count"],
                similarity=float(r["similarity"]),
                score=float(r["score"]),
            )
            for r in rows
        ])

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"v2 search failed: {str(e)}")
