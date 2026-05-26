"""Pull per-statement metadata from v2 needed by the formalization pipeline:
  cache/slogans.pkl     {statement_id: slogan}        (formal prompt, latest per statement)
  cache/decl_names.json {statement_id: decl_name}     (from formal_metadata)

Read-only; regenerates the two artifacts that build_formalization_eval.py and
build_rag_context.py consume. Run after build_formal_index.py / build_split.py.

    python scripts/build_metadata.py
"""
import json
import os
import pickle
import time
from pathlib import Path

import dotenv
dotenv.load_dotenv(os.environ.get("LPR_ENV_FILE", str(Path(__file__).resolve().parent.parent / ".env")))
import boto3
import psycopg2

CACHE = Path(__file__).resolve().parent.parent / "cache"


def connect():
    secret = json.loads(
        boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-west-2"))
        .get_secret_value(SecretId=os.getenv("RDS_SECRET_ARN"))["SecretString"])
    return psycopg2.connect(
        host=os.getenv("RDS_HOST"), port=5432, dbname="v2",
        user=secret["username"], password=secret["password"], sslmode="require",
        connect_timeout=20, options="-c default_transaction_read_only=on -c statement_timeout=120000")


def main():
    conn = connect()
    t0 = time.time()
    with conn.cursor() as c:
        print("pulling formal slogans...")
        c.execute("""SELECT DISTINCT ON (sl.statement_id) sl.statement_id::text, sl.slogan
                     FROM slogan sl WHERE sl.prompt_name = 'formal'
                     ORDER BY sl.statement_id, sl.created_at DESC""")
        slogans = {sid: s for sid, s in c.fetchall()}
        print(f"  slogans: {len(slogans):,}")
        print("pulling decl_names...")
        c.execute("SELECT statement_id::text, decl_name FROM formal_metadata")
        names = {sid: dn for sid, dn in c.fetchall()}
        print(f"  decl_names: {len(names):,}")
    conn.close()
    CACHE.mkdir(exist_ok=True)
    pickle.dump(slogans, open(CACHE / "slogans.pkl", "wb"))
    (CACHE / "decl_names.json").write_text(json.dumps(names))
    print(f"saved slogans.pkl + decl_names.json ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
