from dotenv import load_dotenv
load_dotenv()

import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from db import env_int
from routes.search import router as search_router
from routes.mcp import router as mcp_router
from routes.graph import router as graph_router, warm
from routes.paper_search import router as paper_search_router
from routes.pagerank import router as pagerank_router

# Without an explicit handler, the stdlib's last-resort handler only emits
# WARNING and above, so every logger.info in this app (including the warm-up
# timings) was being dropped from the App Runner log stream. Configure the root
# logger once, here, before anything logs. Override with LOG_LEVEL.
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger(__name__)

# Seconds between background warm-ups. An idle App Runner instance is
# CPU-throttled and lets its outbound connections lapse, so the first search
# after a quiet stretch takes 5-14s against ~0.9s warm — it pays a fresh TLS
# handshake to Nebius, a Secrets Manager fetch, and pool construction. A
# periodic touch keeps all three established, at the cost of the instance
# never going fully idle (it bills at the active rate rather than the lower
# provisioned one). Set API_WARM_INTERVAL_SECONDS=0 to turn the thread off and
# drive GET /warm from an external scheduler instead.
_WARM_INTERVAL = env_int("API_WARM_INTERVAL_SECONDS", 240, minimum=0)
_warm_stop = threading.Event()


def _warm_loop() -> None:
    """Warm once immediately — this is what makes the first request after a
    deploy fast — then every _WARM_INTERVAL seconds until shutdown."""
    while True:
        try:
            # min_interval=0: the loop's own interval is the throttle, so it
            # never has to inherit the public endpoint's floor.
            logger.info("warm-up: %s", warm(min_interval=0))
        except Exception:
            logger.warning("warm-up failed", exc_info=True)
        if _warm_stop.wait(_WARM_INTERVAL):
            return


@asynccontextmanager
async def lifespan(app: FastAPI):
    thread = None
    if _WARM_INTERVAL:
        thread = threading.Thread(target=_warm_loop, name="warmer", daemon=True)
        thread.start()
    yield
    _warm_stop.set()
    if thread is not None:
        thread.join(timeout=5)


app = FastAPI(lifespan=lifespan)

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

@app.get("/ping")
def ping():
    return {"status": "ok"}


@app.get("/warm")
def warm_endpoint():
    """Touch the connection pools and the embedding provider so a real search
    doesn't have to. Safe to call from a scheduler: repeated calls inside
    graph._WARM_MIN_INTERVAL return the previous result instead of re-running."""
    return warm()

app.include_router(search_router)
app.include_router(mcp_router)
app.include_router(graph_router)
app.include_router(paper_search_router)
app.include_router(pagerank_router)

# routes.graph_mcp is intentionally not registered: it imports from the
# deleted routes.search_v2 module and needs to be updated to call the new
# /graph/embedding handler before it can be wired up again.
