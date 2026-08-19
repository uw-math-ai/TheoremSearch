"""Central configuration for the graph_prover experiment.

graph_prover is a thin experiment package: it REUSES experiments/lean_premise_retrieval
(the formal retriever, splits, gold labels, typecheck harness) and only adds the
compiler-in-the-loop premise-selection experiment on top. Nothing in
lean_premise_retrieval is modified; its modules are loaded from file so its bare-script
layout (no __init__.py) doesn't matter.

Environment variables (all optional unless a stage needs them):
  LPR_MATHLIB_DIR     built Lean project with `import Mathlib` (compile stages)
  LPR_ENV_FILE        .env with AWS keys + RDS_SECRET_ARN + RDS_HOST (DB stages)
  NEBIUS_API_KEY      query embeddings (arm C, mutation re-query) — read from LPR .env too
  ANTHROPIC_API_KEY   the prover
  GP_PROVER_MODEL     prover model id (default claude-sonnet-4-6, matching the
                      lean_premise_retrieval formalization experiment for comparability)
  GP_CACHE            override cache dir (default experiments/graph_prover/cache)
  GP_RESULTS          override results dir (default experiments/graph_prover/results)
"""
import importlib.util
import os
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PKG_ROOT.parent.parent
LPR_DIR = REPO_ROOT / "experiments" / "lean_premise_retrieval"

CACHE_DIR = Path(os.environ.get("GP_CACHE", PKG_ROOT / "cache"))
RESULTS_DIR = Path(os.environ.get("GP_RESULTS", PKG_ROOT / "results"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

LPR_CACHE = Path(os.environ.get("LPR_CACHE", LPR_DIR / "cache"))
MATHLIB_DIR = os.environ.get("LPR_MATHLIB_DIR", "")

PROVER_MODEL = os.environ.get("GP_PROVER_MODEL", "claude-sonnet-4-6")
SEED = 42

# Experiment constants (approved plan §Step 2)
BUDGET_K = 6          # compile attempts per task, every arm
POOL_K = 30           # premise pool size offered to the prover
BEAM_WIDTH = 4        # arm E
RRF_K = 60            # rank-fusion constant, same as eval_mpr.py

# Retrieval query embedding — must match the corpus embedding space
# (source: experiments/leansearch_v2_replication/eval_mpr.py).
EMBED_MODEL = "qwen3-8b"
QUERY_INSTRUCTION = ("Given a math search query, retrieve theorems mathematically "
                     "equivalent to the query.\n")
MATHLIB_EXTERNAL_IDS = ["Mathlib_v427", "Mathlib_v428", "Mathlib_v429"]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def lpr_config():
    """experiments/lean_premise_retrieval/config.py (get_rds_conn, CACHE_DIR, ...)."""
    return _load_module("lpr_config", LPR_DIR / "config.py")


def load_formal_retriever():
    """FormalRetriever over the LPR cache index (arm A core)."""
    mod = _load_module("lpr_formal_retriever", LPR_DIR / "src" / "formal_retriever.py")
    return mod.FormalRetriever(LPR_CACHE / "formal_emb.f16.npy",
                               LPR_CACHE / "formal_ids.json",
                               slogans_path=LPR_CACHE / "slogans.pkl")


def load_run_typecheck():
    """The batched statement typechecker (mining-time sanity gate)."""
    return _load_module("lpr_run_typecheck", LPR_DIR / "scripts" / "run_typecheck.py")


def get_rds_conn(statement_timeout_ms: int = 120_000):
    """Read-only psycopg2 connection to RDS v2 via the LPR credential path."""
    return lpr_config().get_rds_conn(statement_timeout_ms=statement_timeout_ms)


def make_nebius_client():
    """OpenAI-compatible client for query embeddings.

    Copied pattern from experiments/leansearch_v2_replication/eval_mpr.py::make_oai.
    NEBIUS_API_KEY comes from the process env or the LPR .env file.
    """
    from openai import OpenAI
    key = os.environ.get("NEBIUS_API_KEY")
    if not key:
        import dotenv
        env_file = os.environ.get("LPR_ENV_FILE", str(LPR_DIR / ".env"))
        dotenv.load_dotenv(env_file)
        key = os.environ.get("NEBIUS_API_KEY")
    if not key:
        raise RuntimeError("NEBIUS_API_KEY not set (env or LPR .env)")
    return OpenAI(base_url="https://api.studio.nebius.ai/v1/", api_key=key)
