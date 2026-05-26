"""Central configuration — all machine-specific paths live here, overridable by env vars.

Defaults keep everything inside the repo (cache/) so a fresh clone + a filled-in .env is
self-contained for the local pipeline. External build dirs (Mathlib, the target library) and
the RDS connection are pointed at via env vars; see .env.example and docs/SETUP.md.
"""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
CACHE_DIR = Path(os.environ.get("LPR_CACHE", REPO_ROOT / "cache"))
ENV_FILE = os.environ.get("LPR_ENV_FILE", str(REPO_ROOT / ".env"))

# Built Lean projects (for the typecheck harness / unfamiliar-library experiment).
# Point these at your local builds; see docs/SETUP.md for how to create them.
MATHLIB_DIR = os.environ.get("LPR_MATHLIB_DIR", "")  # a project with `import Mathlib` built
LIB_DIR = os.environ.get("LPR_LIB_DIR", "")          # the unfamiliar target library, built

CACHE_DIR.mkdir(parents=True, exist_ok=True)


def get_rds_conn(dbname: str = "v2", statement_timeout_ms: int = 0):
    """Read-only psycopg2 connection to the v2 RDS database. Credentials come from ENV_FILE
    (AWS keys + RDS_SECRET_ARN + RDS_HOST); see .env.example. Never writes to v2."""
    import json
    import dotenv
    import boto3
    import psycopg2
    dotenv.load_dotenv(ENV_FILE)
    secret = json.loads(
        boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-west-2"))
        .get_secret_value(SecretId=os.environ["RDS_SECRET_ARN"])["SecretString"])
    return psycopg2.connect(
        host=os.environ["RDS_HOST"], port=5432, dbname=dbname,
        user=secret["username"], password=secret["password"], sslmode="require",
        connect_timeout=20,
        options=f"-c default_transaction_read_only=on -c statement_timeout={statement_timeout_ms}")
