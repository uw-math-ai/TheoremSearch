import json
from fastapi import APIRouter, Request
from routes.search_v2 import search as v2_search
from routes.graph import _traverse, _build_subgraph
from db import rds_conn

router = APIRouter()

MCP_SEARCH_TOOL = {
    "name": "theorem_search",
    "description": (
        "Search for mathematical theorems, lemmas, and definitions using semantic similarity. "
        "Returns results with statement_id UUIDs that can be passed directly to "
        "get_statement or navigate_graph."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "n_results": {"type": "integer", "default": 10},
            "sources": {"type": "array", "items": {"type": "string"}, "default": [], "description": "e.g. 'arXiv', 'Stacks Project'"},
            "types": {"type": "array", "items": {"type": "string"}, "default": [], "description": "e.g. 'theorem', 'lemma', 'definition'"},
            "authors": {"type": "array", "items": {"type": "string"}, "default": [], "description": "Author substring filters"},
            "min_citations": {"type": "integer", "default": 0},
            "citation_weight": {"type": "number", "default": 0.0, "description": "Boost score by ln(citations) * this weight"},
            "in_journal": {"type": ["boolean", "null"], "default": None, "description": "Filter to journal-published papers only"},
        },
        "required": ["query"],
    },
}

MCP_GET_STATEMENT_TOOL = {
    "name": "get_statement",
    "description": (
        "Retrieve full details for a specific informal statement by ID, including its body, proof, "
        "slogan, and the paper it belongs to. Only works for informal (NL/LaTeX) statements. "
        "Use this to hydrate a statement_id returned by theorem_search or navigate_graph."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "statement_id": {"type": "string", "description": "UUID of the statement"},
        },
        "required": ["statement_id"],
    },
}

MCP_NAVIGATE_GRAPH_TOOL = {
    "name": "navigate_graph",
    "description": (
        "Traverse the informal (NL/LaTeX) dependency graph from a given statement. "
        "Only operates on informal statements — formal Lean declarations are not included. "
        "Returns the reachable statement nodes (with slogans) and the dependency edges between them. "
        "direction='dependency' follows what this statement uses (its children / prerequisites). "
        "direction='dependent' finds what uses this statement (its parents / dependents). "
        "direction='both' returns both directions. "
        "Each node includes its statement_id, name, slogan, and BFS depth from the origin. "
        "Each edge includes source/target IDs, location (body/proof/note), and detection methods."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "statement_id": {
                "type": "string",
                "description": "UUID of the starting statement",
            },
            "direction": {
                "type": "string",
                "enum": ["dependency", "dependent", "both"],
                "default": "dependency",
                "description": (
                    "'dependency' = what this statement uses (children); "
                    "'dependent' = what uses this statement (parents); "
                    "'both' = both directions"
                ),
            },
            "depth": {
                "type": "integer",
                "default": 1,
                "minimum": 1,
                "maximum": 5,
                "description": "Number of hops to traverse from the origin statement",
            },
        },
        "required": ["statement_id"],
    },
}

MCP_TOOLS = [MCP_SEARCH_TOOL, MCP_GET_STATEMENT_TOOL, MCP_NAVIGATE_GRAPH_TOOL]


def _mcp_success(request_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _mcp_error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


async def _handle_theorem_search(args: dict) -> dict:
    search_response = await v2_search(
        query=args["query"],
        n_results=args.get("n_results", 10),
        sources=args.get("sources", []),
        types=args.get("types", []),
        authors=args.get("authors", []),
        min_citations=args.get("min_citations", 0),
        citation_weight=args.get("citation_weight", 0.0),
        in_journal=args.get("in_journal"),
    )
    response_payload = search_response.model_dump()
    return {
        "content": [{"type": "text", "text": json.dumps(response_payload)}],
        "structuredContent": response_payload,
    }


def _handle_get_statement(args: dict) -> dict:
    statement_id = args.get("statement_id")
    if not statement_id:
        raise ValueError("statement_id is required")

    with rds_conn("v2") as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.statement_id, s.kind, s.body, s.proof,
                   im.ref, im.note,
                   p.paper_id, p.external_id, p.title, p.url, p.authors
            FROM statement s
            LEFT JOIN informal_metadata im ON im.statement_id = s.statement_id
            JOIN paper p ON p.paper_id = s.paper_id
            WHERE s.statement_id = %s AND s.formality = 'informal'
            """,
            (statement_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"No informal statement with id '{statement_id}'")

        cur.execute(
            """
            SELECT slogan FROM slogan
            WHERE statement_id = %s AND NOT insufficient_context
            ORDER BY created_at LIMIT 1
            """,
            (statement_id,),
        )
        slogan_row = cur.fetchone()

    sid, kind, body, proof, ref, note, paper_id, paper_ext_id, paper_title, url, authors = row
    result = {
        "statement_id": str(sid),
        "kind": kind,
        "ref": ref,
        "body": body or "",
        "proof": proof,
        "note": note,
        "slogan": slogan_row[0] if slogan_row else None,
        "paper_id": str(paper_id),
        "paper_external_id": paper_ext_id,
        "paper_title": paper_title,
        "paper_url": url,
        "authors": authors or [],
    }
    return {
        "content": [{"type": "text", "text": json.dumps(result)}],
        "structuredContent": result,
    }


def _handle_navigate_graph(args: dict) -> dict:
    statement_id = args.get("statement_id")
    direction = args.get("direction", "dependency")
    depth = int(args.get("depth", 1))

    if not statement_id:
        raise ValueError("statement_id is required")
    if direction not in ("dependency", "dependent", "both"):
        raise ValueError("direction must be 'dependency', 'dependent', or 'both'")
    if not (1 <= depth <= 5):
        raise ValueError("depth must be between 1 and 5")

    with rds_conn("v2") as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM statement WHERE statement_id = %s AND formality = 'informal'",
            (statement_id,),
        )
        if cur.fetchone() is None:
            raise ValueError(f"No informal statement with id '{statement_id}'")
        node_depth = _traverse(cur, [statement_id], depth, direction)
        subgraph = _build_subgraph(cur, node_depth)

    result = subgraph.model_dump()
    return {
        "content": [{"type": "text", "text": json.dumps(result)}],
        "structuredContent": result,
    }


@router.api_route("/graph_mcp", methods=["GET", "POST"])
async def graph_mcp(request: Request):
    if request.method == "GET":
        return {
            "name": "TheoremSearch Graph MCP",
            "version": "1.0.0",
            "endpoint": "/graph_mcp",
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
                "serverInfo": {"name": "TheoremSearch Graph MCP", "version": "1.0.0"},
            },
        )

    if method == "tools/list":
        return _mcp_success(request_id, {"tools": MCP_TOOLS})

    if method == "tools/call":
        params = body.get("params") or {}
        tool_name = params.get("name")
        args = params.get("arguments") or {}

        try:
            if tool_name == "theorem_search":
                result = await _handle_theorem_search(args)
            elif tool_name == "get_statement":
                result = _handle_get_statement(args)
            elif tool_name == "navigate_graph":
                result = _handle_navigate_graph(args)
            else:
                return _mcp_error(request_id, -32601, f"Unknown tool: {tool_name}")
        except ValueError as e:
            return _mcp_error(request_id, -32602, str(e))
        except Exception as e:
            return _mcp_error(request_id, -32603, str(e))

        return _mcp_success(request_id, result)

    return _mcp_error(request_id, -32601, f"Method not found: {method}")
