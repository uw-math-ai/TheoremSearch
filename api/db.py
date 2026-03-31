import os
import json
import boto3
from contextlib import contextmanager
from psycopg2.pool import SimpleConnectionPool

_conn_pools: dict[str, SimpleConnectionPool] = {}

def _get_secret() -> dict:
    region = os.getenv("AWS_REGION", "us-west-2")
    secret_arn = os.getenv("RDS_SECRET_ARN")
    sm = boto3.client("secretsmanager", region_name=region)
    secret_value = sm.get_secret_value(SecretId=secret_arn)
    return json.loads(secret_value["SecretString"])

def get_pool(dbname: str) -> SimpleConnectionPool:
    if dbname not in _conn_pools:
        secret = _get_secret()
        _conn_pools[dbname] = SimpleConnectionPool(
            1, 10,
            host=os.getenv("RDS_HOST") or secret.get("host"),
            port=int(secret.get("port", 5432)),
            dbname=dbname,
            user=secret["username"],
            password=secret["password"],
            sslmode="require",
        )
    return _conn_pools[dbname]

@contextmanager
def rds_conn(dbname: str = "postgres"):
    conn = get_pool(dbname).getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        get_pool(dbname).putconn(conn)
