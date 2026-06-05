import json
from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from models import SearchRequest
from routes.search import search

router = APIRouter()

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
            "prompt": {"type": ["string", "null"], "default": None, "description": "Instruction prompt prepended to query before embedding. If null, uses the default prompt."},
            "db_top_k": {"type": ["integer", "null"], "default": None, "description": "Number of ANN candidates to retrieve before reranking. Higher values improve recall at cost of latency. Default: 2 * n_results."},
        },
        "required": ["query"],
    },
}


def _mcp_success(request_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _mcp_error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


@router.api_route("/mcp", methods=["GET", "POST"])
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

    if method == "ping":
        return _mcp_success(request_id, {})

    if method == "tools/list":
        return _mcp_success(request_id, {"tools": [MCP_SEARCH_TOOL]})

    if method == "tools/call":
        params = body.get("params") or {}
        tool_name = params.get("name")

        if tool_name != MCP_SEARCH_TOOL["name"]:
            return _mcp_error(request_id, -32601, "Unknown tool")

        try:
            payload = SearchRequest(**(params.get("arguments") or {}))
            # `search` is a sync function doing blocking I/O; run it in the
            # threadpool so this async MCP handler doesn't block the event loop.
            search_response = await run_in_threadpool(search, payload, mcp=True)
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
