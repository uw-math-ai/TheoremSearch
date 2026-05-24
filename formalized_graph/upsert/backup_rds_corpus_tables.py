"""Snapshot the four RDS tables that anchor the corpus_v3 → slogan/embedding chain.

Backs up `statement`, `formal_metadata`, `slogan`, `embedding` to a timestamped
directory of gzipped CSVs plus a manifest.json with row counts and SHA-256
checksums.

The point: if a corpus_v3 re-ingest or paper_id remap goes sideways, we can
restore these tables without losing any LLM-generated slogans or computed
embeddings. (Those are expensive to regenerate.)

Auth: reads RDS connection from .env at TheoremSearch root using the same
AWS Secrets Manager pattern as prod/rds.py.

NETWORK REQUIREMENT: The RDS cluster is in a private VPC. Run this from a
host with VPC egress to the cluster (typically your local laptop on UW VPN,
NOT from klone/HYAK login or compute nodes — those lack DNS/network reach
to the cluster's `rds.amazonaws.com` hostname).

Usage (from a network-reachable host):
  python3 formalized_graph/upsert/backup_rds_corpus_tables.py
  python3 formalized_graph/upsert/backup_rds_corpus_tables.py --out /path/to/dir
  python3 formalized_graph/upsert/backup_rds_corpus_tables.py --tag pre_remap

One-time setup (if your interpreter lacks them):
  python3 -m pip install --user boto3 psycopg2-binary
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# --- env loading ------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = REPO_ROOT / ".env"


def load_env(path: Path) -> None:
    """Minimal .env loader — sets os.environ for any KEY=VAL lines not already set."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


# --- connection -------------------------------------------------------------


def get_rds_connection():
    """Mirror prod/rds.py — AWS Secrets Manager → psycopg2 connection."""
    import boto3
    import psycopg2

    region = os.environ.get("AWS_REGION")
    secret_arn = os.environ.get("RDS_SECRET_ARN")
    host_override = os.environ.get("RDS_HOST") or os.environ.get("RDS_WRITER_HOST")
    dbname_override = os.environ.get("RDS_DBNAME")  # secret typically lacks dbname

    if not (region and secret_arn):
        sys.exit("missing AWS_REGION or RDS_SECRET_ARN in env (.env at repo root?)")

    sm = boto3.client("secretsmanager", region_name=region)
    secret = json.loads(sm.get_secret_value(SecretId=secret_arn)["SecretString"])

    conn = psycopg2.connect(
        host=host_override or secret.get("host"),
        port=int(secret.get("port", 5432)),
        dbname=dbname_override or secret.get("dbname") or "postgres",
        user=secret["username"],
        password=secret["password"],
        sslmode="require",
    )
    conn.autocommit = True
    return conn


# --- dump -------------------------------------------------------------------

TABLES = ["statement", "formal_metadata", "slogan", "embedding"]


def dump_table(conn, table: str, out_path: Path) -> tuple[int, str]:
    """COPY a single table to a gzip CSV. Returns (rowcount, sha256 of CSV stream)."""
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    row_count = cur.fetchone()[0]

    sha = hashlib.sha256()

    class _Sink:
        """Write target that gzip-encodes + checksums the stream as psycopg2 emits it."""
        def write(self, b):
            if isinstance(b, str):
                b = b.encode()
            sha.update(b)
            gz.write(b)

    with gzip.open(out_path, "wb", compresslevel=6) as gz:
        cur.copy_expert(
            f"COPY {table} TO STDOUT WITH (FORMAT csv, HEADER true)",
            _Sink(),
        )
    return row_count, sha.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=Path("/gscratch/amath/simku22/rds_backups"),
                    help="base output directory; a timestamped subdir is created inside")
    ap.add_argument("--tag", type=str, default="",
                    help="optional snapshot tag (e.g. 'pre_remap') — included in subdir name")
    args = ap.parse_args()

    load_env(ENV_PATH)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sub = f"snap_{args.tag}_{ts}" if args.tag else f"snap_{ts}"
    out_dir = args.out / sub
    out_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(out_dir, 0o700)
    print(f"snapshot dir: {out_dir}", flush=True)

    conn = get_rds_connection()

    manifest = {
        "created_at": ts,
        "tag": args.tag or None,
        "tables": {},
        "env_used": {k: os.environ.get(k, "") for k in ("AWS_REGION", "RDS_HOST", "RDS_WRITER_HOST")
                     if os.environ.get(k)},
    }

    for tbl in TABLES:
        out_path = out_dir / f"{tbl}.csv.gz"
        print(f"  dumping {tbl} → {out_path.name} ...", end=" ", flush=True)
        try:
            n_rows, digest = dump_table(conn, tbl, out_path)
            size = out_path.stat().st_size
            os.chmod(out_path, 0o600)
            manifest["tables"][tbl] = {
                "rows": n_rows,
                "bytes_gz": size,
                "sha256_uncompressed_stream": digest,
            }
            print(f"{n_rows:,} rows, {size/1e6:.1f} MB")
        except Exception as e:
            manifest["tables"][tbl] = {"error": repr(e)}
            print(f"FAILED: {e!r}")

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    os.chmod(manifest_path, 0o600)
    print(f"\nmanifest: {manifest_path}")
    print(json.dumps(manifest["tables"], indent=2))

    # Summary
    ok = sum(1 for t in manifest["tables"].values() if "rows" in t)
    if ok == len(TABLES):
        print(f"\nDONE — all {ok}/{len(TABLES)} tables backed up.")
        return 0
    print(f"\nPARTIAL — {ok}/{len(TABLES)} tables backed up (see errors above).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
