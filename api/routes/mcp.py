"""MCP server under /mcp, backed by the v2 corpus.

Migrated off v1 on 2026-10-02. It previously delegated to routes.search, which
reads theorem_search_qwen8b in the v1 `postgres` database; it now runs the same
filtered vector search the website uses, over v2 — 12.2M embedded statements
against v1's 9.3M, plus 390k formal Lean declarations and nine sources rather
than seven.

The tool name and every v1 argument name are kept, because the arguments are
in use: across 30 days clients sent sources 216 times, paper_filter 189,
year_range 160, types 85, citation_weight 81, authors 57 and tags 37, out of
3,793 calls. Two things do change observably:

  - Integer slogan_id / theorem_id are gone. v2 keys on UUIDs, so results
    carry statement_id and paper_id instead. Those are exactly what
    /graph/statement/{id} and /graph/paper/{id} accept, which is the point of
    moving: an agent can now follow a result into the dependency graph.
  - v1 filtered in Python after retrieval, so a filtered search could return
    fewer than n_results (or nothing) even when matches existed. v2 filters
    inside the query, so filtered searches fill up to n_results.

Query logging still writes to v1's api_search_query, which is what the query
dashboard reads. That is MCP's one remaining dependency on v1.
"""
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool

from db import rds_conn
from routes.graph import (
    _RERANK_MIN,
    _embed_query,
    _execute_search,
    _search_params,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_SERVER_NAME = "TheoremSearch MCP"
_SERVER_VERSION = "2.0.0"   # bumped: results key on v2 UUIDs, not v1 integers

MCP_SEARCH_TOOL = {
    "name": "theorem_search",
    "description": (
        "Search mathematical statements by meaning. Each result carries a "
        "statement_id (UUID) accepted by GET /graph/statement/{statement_id} "
        "for walking the dependency graph, and a paper_id for "
        "GET /graph/paper/{paper_id}. Covers arXiv, the Stacks Project, "
        "ProofWiki, four open textbooks, and formal Lean declarations."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "n_results": {"type": "integer", "default": 10},
            "formality": {
                "type": "string",
                "enum": ["informal", "formal", "both"],
                "default": "informal",
                "description": (
                    "informal: prose statements from papers and textbooks. "
                    "formal: Lean declarations (source 'Lean Repo' only). "
                    "both: either. Defaults to informal, which is what this "
                    "tool returned before formal statements existed."
                ),
            },
            "sources": {
                "type": "array", "items": {"type": "string"}, "default": [],
                "description": "e.g. 'arXiv', 'Stacks Project', 'ProofWiki', 'Lean Repo'.",
            },
            "authors": {
                "type": "array", "items": {"type": "string"}, "default": [],
                "description": "Case-insensitive substring match against any author.",
            },
            "types": {
                "type": "array", "items": {"type": "string"}, "default": [],
                "description": "e.g. 'theorem', 'lemma', 'proposition', 'corollary', 'definition'.",
            },
            "tags": {
                "type": "array", "items": {"type": "string"}, "default": [],
                "description": "Primary arXiv category, e.g. 'math.NT'. Alias: categories.",
            },
            "categories": {
                "type": "array", "items": {"type": "string"}, "default": [],
                "description": "Same as tags; whichever is supplied is used.",
            },
            "paper_filter": {
                "type": ["string", "null"], "default": None,
                "description": (
                    "Comma-separated arXiv IDs or title substrings. arXiv IDs "
                    "match as a prefix; other tokens match title substrings."
                ),
            },
            "year_range": {
                "type": ["array", "null"], "items": {"type": "integer"}, "default": None,
                "description": (
                    "[min, max] on the paper's latest version. Statements with "
                    "no known year pass this filter, where v1 dropped them."
                ),
            },
            "citation_range": {
                "type": ["array", "null"], "items": {"type": "integer"}, "default": None,
                "description": "[min, max] citation count.",
            },
            "citation_weight": {
                "type": "number", "default": 0.0,
                "description": "Boost the score by ln(citations) times this weight.",
            },
            "include_unknown_citations": {
                "type": "boolean", "default": True,
                "description": "Whether papers with no known citation count pass citation_range.",
            },
            "in_journal": {
                "type": ["boolean", "null"], "default": None,
                "description": (
                    "true: only papers with a journal reference; false: only "
                    "preprints. Sources without publication metadata pass either way."
                ),
            },
            "prompt": {
                "type": ["string", "null"], "default": None,
                "description": (
                    "Advanced. Replaces the instruction prefix placed in front "
                    "of the query before embedding, verbatim, so you own any "
                    "trailing 'Query: '. Leave null to use the prefix the v2 "
                    "corpus was built against; an override changes retrieval "
                    "behaviour, and it is not the string v1 defaulted to."
                ),
            },
            "db_top_k": {
                "type": ["integer", "null"], "default": None,
                "description": (
                    "Advanced. ANN candidates retrieved before reranking. "
                    "Higher improves recall and costs latency. Clamped to "
                    "[120, 1000]; leave null to size it from n_results."
                ),
            },
        },
        "required": ["query"],
    },
}

_TOOLS = [MCP_SEARCH_TOOL]


def _mcp_success(request_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _mcp_error(request_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _pair(value: Optional[List[int]]) -> Tuple[Optional[int], Optional[int]]:
    """[min, max] -> (min, max); anything else -> (None, None), matching v1,
    which ignored a range that was not exactly two elements."""
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return value[0], value[1]
    return None, None


def _log_query(args: dict) -> None:
    """Record the call in v1's api_search_query, which the query dashboard
    reads. Best-effort and deliberately swallowing: that table lives in the
    other database, and trouble there must not cost a caller their results."""
    year_min, year_max = _pair(args.get("year_range"))
    cit_min, cit_max = _pair(args.get("citation_range"))
    try:
        with rds_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO api_search_query (
                    query_at, query, n_results, source, authors, types, tags,
                    paper_filter, year_range, citation_range, citation_weight,
                    include_unknown_citations, mcp
                ) VALUES (NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                """,
                (
                    args.get("query"),
                    args.get("n_results") or 10,
                    args.get("sources") or None,
                    args.get("authors") or None,
                    args.get("types") or None,
                    (args.get("tags") or args.get("categories")) or None,
                    args.get("paper_filter"),
                    [year_min, year_max] if year_min is not None else None,
                    [cit_min, cit_max] if cit_min is not None else None,
                    args.get("citation_weight") or 0.0,
                    args.get("include_unknown_citations", True),
                ),
            )
    except Exception:
        logger.warning("MCP query logging to v1 failed", exc_info=True)


def _result(row: dict) -> dict:
    """One v2 row in the shape this tool has always returned — statement
    fields flat, paper nested. statement_id, paper_id and formality are new."""
    return {
        "statement_id": str(row["statement_id"]),
        "paper_id": str(row["paper_id"]),
        "name": row.get("name"),
        "theorem_type": row.get("kind"),
        "formality": row.get("formality"),
        # Formal statements carry a Lean signature in body; where the ingest
        # never captured one, the docstring is the only prose available.
        "body": row.get("body") or row.get("docstring"),
        "slogan": row.get("slogan"),
        "link": row.get("url") or None,
        "source": row.get("source"),
        "paper": {
            "paper_id": str(row["paper_id"]),
            "title": row.get("title"),
            "authors": row.get("authors") or [],
            "external_id": row.get("external_id"),
            "categories": row.get("categories") or [],
            "year": row.get("year"),
            "journal_ref": row.get("journal_ref"),
            "journal_published": row.get("journal_ref") is not None,
            "citations": row.get("citation_count"),
            "source": row.get("source"),
        },
        "similarity": float(row["similarity"]),
        "score": float(row["score"]),
    }


def _run_search(args: dict) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        raise ValueError("query is required and must be a non-empty string")

    n_results = max(1, min(int(args.get("n_results") or 10), 100))
    year_min, year_max = _pair(args.get("year_range"))
    cit_min, cit_max = _pair(args.get("citation_range"))
    formality = args.get("formality") or "informal"
    if formality not in ("informal", "formal", "both"):
        raise ValueError("formality must be one of: informal, formal, both")

    query_vec = _embed_query(query, args.get("prompt"))
    params = _search_params(
        query_vec,
        n_results=n_results,
        formality=formality,
        sources=args.get("sources") or None,
        types=args.get("types") or None,
        authors=args.get("authors") or None,
        # v1 called this `tags` and matched primary_category — the same column
        # v2's `categories` filters on, so the mapping is exact.
        categories=(args.get("tags") or args.get("categories")) or None,
        min_citations=cit_min or 0,
        citation_max=cit_max,
        # v1's schema defaults this True; v2's own default is None ("count
        # unknown as zero"), so it has to be passed through explicitly.
        include_unknown_citations=bool(args.get("include_unknown_citations", True)),
        citation_weight=float(args.get("citation_weight") or 0.0),
        in_journal=args.get("in_journal"),
        year_min=year_min,
        year_max=year_max,
        paper_filter=args.get("paper_filter"),
    )

    db_top_k = args.get("db_top_k")
    if db_top_k:
        # Feeds a LIMIT and the HNSW iterative scan, so keep it sane: never
        # below the rerank window, never above pgvector's ef_search ceiling.
        params["ann_k"] = max(_RERANK_MIN, min(int(db_top_k), 1000))

    rows = _execute_search(params, "full")
    return {"theorems": [_result(r) for r in rows]}


@router.api_route("/mcp", methods=["GET", "POST"])
async def mcp(request: Request):
    if request.method == "GET":
        return {
            "name": _SERVER_NAME,
            "version": _SERVER_VERSION,
            "endpoint": "/mcp",
            "methods": ["initialize", "ping", "tools/list", "tools/call"],
        }

    try:
        body = await request.json()
    except Exception:
        return _mcp_error(None, -32700, "Parse error: body is not valid JSON")
    if not isinstance(body, dict):
        return _mcp_error(None, -32600, "Invalid request: body must be a JSON object")

    request_id = body.get("id")
    method = body.get("method")

    if method == "initialize":
        return _mcp_success(request_id, {
            "protocolVersion": "2025-06-18",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": _SERVER_NAME, "version": _SERVER_VERSION},
        })

    if method == "ping":
        return _mcp_success(request_id, {})

    if method == "tools/list":
        return _mcp_success(request_id, {"tools": _TOOLS})

    if method == "tools/call":
        params = body.get("params") or {}
        if params.get("name") != MCP_SEARCH_TOOL["name"]:
            return _mcp_error(request_id, -32601, "Unknown tool")

        args: Dict[str, Any] = params.get("arguments") or {}
        try:
            # _run_search blocks — an embedding HTTP call plus psycopg2
            # queries — so it must stay off the event loop: one blocking call
            # there serializes every request on the instance.
            payload = await run_in_threadpool(_run_search, args)
        except ValueError as e:
            return _mcp_error(request_id, -32602, str(e))
        except Exception as e:
            logger.exception("MCP theorem_search failed")
            return _mcp_error(request_id, -32603, f"{type(e).__name__}: {e}")

        # Logged after the search, so a logging failure cannot cost results.
        await run_in_threadpool(_log_query, {**args, "n_results": len(payload["theorems"])})

        return _mcp_success(request_id, {
            "content": [{"type": "text", "text": json.dumps(payload)}],
            "structuredContent": payload,
        })

    return _mcp_error(request_id, -32601, f"Method not found: {method}")
