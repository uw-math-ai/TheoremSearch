import os
import json
import logging
import threading
import boto3
from contextlib import contextmanager

from psycopg2 import OperationalError
from psycopg2.pool import ThreadedConnectionPool


logger = logging.getLogger(__name__)

_conn_pools: dict[str, ThreadedConnectionPool] = {}
# Guards _conn_pools and the cached secret. Pools are built lazily from several
# sync route handlers running in FastAPI's threadpool, so creation, teardown,
# and rebuild-on-auth-failure must be serialized.
_pools_lock = threading.Lock()

# Cached copy of the RDS secret. The secret ARN is an RDS-managed master-user
# secret that AUTO-ROTATES (default every 7 days); if we cached the password
# for the life of the process (the old @lru_cache behavior) every rotation
# would silently break fresh connections until a manual redeploy. Instead we
# cache it, but drop the cache and rebuild the pool whenever a connection fails
# to authenticate — see rds_conn.
_secret_cache: dict | None = None
_secret_lock = threading.Lock()


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


def _fetch_secret() -> dict:
    region = os.getenv("AWS_REGION", "us-west-2")
    secret_arn = os.getenv("RDS_SECRET_ARN")
    sm = boto3.client("secretsmanager", region_name=region)
    secret_value = sm.get_secret_value(SecretId=secret_arn)
    return json.loads(secret_value["SecretString"])


def _get_secret(force_refresh: bool = False) -> dict:
    """Return the RDS secret, fetching from Secrets Manager on first use or
    when ``force_refresh`` is set (i.e. after an auth failure that suggests the
    password rotated under us)."""
    global _secret_cache
    if _secret_cache is not None and not force_refresh:
        return _secret_cache
    with _secret_lock:
        if _secret_cache is None or force_refresh:
            _secret_cache = _fetch_secret()
        return _secret_cache


def _build_pool(dbname: str, secret: dict) -> ThreadedConnectionPool:
    return ThreadedConnectionPool(
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


def get_pool(dbname: str) -> ThreadedConnectionPool:
    pool = _conn_pools.get(dbname)
    if pool is not None:
        return pool
    with _pools_lock:
        # Re-check under the lock: another thread may have just built it.
        pool = _conn_pools.get(dbname)
        if pool is None:
            pool = _build_pool(dbname, _get_secret())
            _conn_pools[dbname] = pool
        return pool


def _rebuild_pool(dbname: str) -> ThreadedConnectionPool:
    """Drop the pool for ``dbname`` and rebuild it against a freshly fetched
    secret. Called after an auth failure, which for an RDS-managed secret
    almost always means the password rotated and our cached copy (and every
    connection in the old pool) is stale."""
    with _pools_lock:
        old = _conn_pools.pop(dbname, None)
        if old is not None:
            try:
                old.closeall()
            except Exception:
                logger.warning("Failed to close stale pool for %s", dbname, exc_info=True)
        secret = _get_secret(force_refresh=True)
        pool = _build_pool(dbname, secret)
        _conn_pools[dbname] = pool
        return pool


def _is_auth_failure(exc: OperationalError) -> bool:
    """True if the error looks like a password/auth rejection rather than a
    transient network blip. psycopg2 doesn't always populate pgcode for
    connection-time failures (the server rejects before a session exists), so
    fall back to matching the message."""
    if getattr(exc, "pgcode", None) == "28P01":  # invalid_password
        return True
    msg = str(exc).lower()
    return "password authentication failed" in msg or "authentication failed" in msg


def _acquire_live_conn(dbname: str):
    """Get a connection from the pool and confirm it's usable. Returns
    (pool, conn). Raises OperationalError on auth failure so the caller can
    decide whether to rebuild the pool."""
    pool = get_pool(dbname)
    conn = pool.getconn()
    # Cheap liveness check: recycle the connection if RDS killed it while
    # idle. One extra ~1ms roundtrip; saves the request from a hard fail.
    try:
        with conn.cursor() as c:
            c.execute("SELECT 1")
    except OperationalError:
        # A non-auth blip (idle-killed socket): drop this one and take another
        # from the same pool. An auth failure here surfaces on the fresh
        # getconn below and propagates to rds_conn's rebuild path.
        pool.putconn(conn, close=True)
        conn = pool.getconn()
    return pool, conn


@contextmanager
def rds_conn(dbname: str = "postgres"):
    try:
        pool, conn = _acquire_live_conn(dbname)
    except OperationalError as e:
        if not _is_auth_failure(e):
            raise
        # Password almost certainly rotated (RDS-managed secret auto-rotates).
        # Refresh the secret, rebuild the pool, and try once more. If this
        # still fails the credential really is wrong and the error propagates.
        logger.warning(
            "Auth failure opening %s connection; refreshing secret and "
            "rebuilding pool (likely RDS secret rotation)", dbname,
        )
        _rebuild_pool(dbname)
        pool, conn = _acquire_live_conn(dbname)

    try:
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
