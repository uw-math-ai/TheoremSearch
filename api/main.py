from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes.search import router as search_router
from routes.search_v2 import router as search_v2_router
from routes.mcp import router as mcp_router
from routes.graph import router as graph_router
from routes.graph_mcp import router as graph_mcp_router
from routes.paper_search import router as paper_search_router

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://graph.theoremsearch.com",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(search_router)
app.include_router(search_v2_router, prefix="/v2")
app.include_router(mcp_router)
app.include_router(graph_mcp_router)
app.include_router(graph_router)
app.include_router(paper_search_router)
