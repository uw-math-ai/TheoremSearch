from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from routes.search import router as search_router
from routes.mcp import router as mcp_router
from routes.graph import router as graph_router

app = FastAPI()

app.include_router(search_router)
app.include_router(mcp_router)
app.include_router(graph_router)
