import os
import json
import logging
import boto3
from contextlib import contextmanager
from functools import lru_cache

from psycopg2 import OperationalError
from psycopg2.pool import ThreadedConnectionPool


logger = logging.getLogger(__name__)

_conn_pools: dict[str, ThreadedConnectionPool] = {}


def _env_int(name: str, default: int) -> int:
    """Positive int from the environment, falling back to `default` when the
    var is unset, blank, non-numeric, or non-positive. A non-empty but invalid
    value is logged so a misconfigured deploy is diagnosable instead of
    silently running on the default."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        val = int(raw)
    except ValueError:
        logger.warning("%s=%r is not an integer; using default %d", name, raw, default)
        return default
    if val <= 0:
        logger.warning("%s=%d must be positive; using default %d", name, val, default)
        return default
    return val


# Caps any single query at 10s — runaway queries would otherwise pin a
# connection forever and eventually deadlock the pool. Override with
# RDS_STATEMENT_TIMEOUT_MS.
_STATEMENT_TIMEOUT_MS = _env_int("RDS_STATEMENT_TIMEOUT_MS", 10_000)

# Per-process connection-pool bounds. The default max (40) matches FastAPI's
# default sync threadpool size so threadpool workers don't queue on
# getconn() once route handlers are sync def.
#
# CONNECTION BUDGET: each running instance opens up to _POOL_MAX connections
# per distinct dbname. On AWS App Runner the service scales to `MaxSize`
# instances, so the worst-case connection count against the Aurora cluster is
# roughly:  MaxSize × _POOL_MAX × (distinct dbnames in use).  Keep that product
# safely under the cluster's max_connections (Aurora derives it from the
# instance class) or front the cluster with RDS Proxy. Tune per instance via
# RDS_POOL_MIN / RDS_POOL_MAX without a code change.
_POOL_MIN = _env_int("RDS_POOL_MIN", 5)
_POOL_MAX = _env_int("RDS_POOL_MAX", 40)
# ThreadedConnectionPool requires minconn <= maxconn; clamp on misconfig.
if _POOL_MIN > _POOL_MAX:
    logger.warning(
        "RDS_POOL_MIN (%d) > RDS_POOL_MAX (%d); clamping min down to max",
        _POOL_MIN, _POOL_MAX,
    )
    _POOL_MIN = _POOL_MAX


@lru_cache(maxsize=1)
def _get_secret() -> dict:
    region = os.getenv("AWS_REGION", "us-west-2")
    secret_arn = os.getenv("RDS_SECRET_ARN")
    sm = boto3.client("secretsmanager", region_name=region)
    secret_value = sm.get_secret_value(SecretId=secret_arn)
    return json.loads(secret_value["SecretString"])


def get_pool(dbname: str) -> ThreadedConnectionPool:
    if dbname not in _conn_pools:
        secret = _get_secret()
        _conn_pools[dbname] = ThreadedConnectionPool(
            _POOL_MIN, _POOL_MAX,
            host=os.getenv("RDS_HOST") or secret.get("host"),
            port=int(secret.get("port", 5432)),
            dbname=dbname,
            user=secret["username"],
            password=secret["password"],
            sslmode="require",
            # TCP keepalives so the OS notices dead connections after an RDS
            # idle timeout, NAT drop, or failover — instead of handing out a
            # zombie connection that throws on first use.
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=3,
            connect_timeout=5,
            options=f"-c statement_timeout={_STATEMENT_TIMEOUT_MS}",
        )
    return _conn_pools[dbname]


@contextmanager
def rds_conn(dbname: str = "postgres"):
    pool = get_pool(dbname)
    conn = pool.getconn()
    try:
        # Cheap liveness check: recycle the connection if RDS killed it while
        # idle. One extra ~1ms roundtrip; saves the request from a hard fail.
        try:
            with conn.cursor() as c:
                c.execute("SELECT 1")
        except OperationalError:
            pool.putconn(conn, close=True)
            conn = pool.getconn()

        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        pool.putconn(conn)
