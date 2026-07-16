"""Shared client + prompt config for the latex-vs-slogan experiment.

Reads the embedding/chat key from the environment (NEBIUS_API_KEY, falling back
to TOKENFACTORY_API_KEY). Never hard-code a key here. A repo-root `.env` with
`NEBIUS_API_KEY=...` is loaded automatically if present.
"""
import os
import numpy as np
from openai import OpenAI

# --- optional repo-root .env loading (KEY=VALUE lines) -----------------------
def _load_dotenv():
    here = os.path.dirname(os.path.abspath(__file__))
    for root in (here, os.path.dirname(here), os.path.dirname(os.path.dirname(here))):
        p = os.path.join(root, ".env")
        if os.path.exists(p):
            for line in open(p):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
_load_dotenv()

API_KEY = os.environ.get("NEBIUS_API_KEY") or os.environ.get("TOKENFACTORY_API_KEY")
if not API_KEY:
    raise SystemExit("Set NEBIUS_API_KEY (or TOKENFACTORY_API_KEY) in the environment or a .env file.")

BASE_URL = os.environ.get("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/")
client = OpenAI(base_url=BASE_URL, api_key=API_KEY)

EMBED_MODEL = "Qwen/Qwen3-Embedding-8B"
CHAT_MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507"

# Deployed asymmetric instructions (mirror the production retriever).
QUERY_INSTRUCT = (
    "Given an informal description of a mathematical result, retrieve the formal theorem "
    "statement that matches it. The query describes a specific theorem, lemma, or proposition "
    "from a research paper."
)
CORPUS_INSTRUCT = (
    "Represent the given math statement for retrieving related statement by natural language query."
)


def wrap(text, side):
    """Format text with the Qwen3-Embedding instruction wrapper for a given side."""
    ins = QUERY_INSTRUCT if side == "query" else CORPUS_INSTRUCT
    return f"Instruct: {ins}\nQuery:{text}"


def embed(texts, batch=64):
    """Return a list of L2-normalized 4096-d vectors for the given formatted strings."""
    out = []
    for i in range(0, len(texts), batch):
        resp = client.embeddings.create(model=EMBED_MODEL, input=texts[i:i + batch])
        for d in resp.data:
            v = np.asarray(d.embedding, dtype=np.float64)
            out.append(v / np.linalg.norm(v))
    return out
