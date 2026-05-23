import os
import json
import boto3
from contextlib import contextmanager
from functools import lru_cache

from psycopg2 import OperationalError
from psycopg2.pool import ThreadedConnectionPool


_conn_pools: dict[str, ThreadedConnectionPool] = {}

# Caps any single query at 10s — runaway queries would otherwise pin a
# connection forever and eventually deadlock the pool.
_STATEMENT_TIMEOUT_MS = 10_000
# Match FastAPI's default sync threadpool size so threads don't queue on
# getconn() once route handlers are sync def.
_POOL_MIN = 5
_POOL_MAX = 40


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
