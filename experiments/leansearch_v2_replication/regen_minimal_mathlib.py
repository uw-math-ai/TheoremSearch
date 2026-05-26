"""Generate `minimal` prompt slogans for Mathlib v427+v428.

We have ~11.7M `minimal` slogans across the whole corpus but ZERO for
Mathlib v427+v428 (which only got the `formal` prompt). Generating the
`minimal` prompt for Mathlib gives us a 2nd slogan per decl → enables
multi-slogan ensemble retrieval at no eval-side cost.

Uses qwen3-235b on Nebius. Writes to slogan table under
(prompt_name='minimal', model_name='qwen3-235b'). Resume-safe.

Usage:
  python3 regen_minimal_mathlib.py --shard 0 --n-shards 16 --workers 8
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3
import psycopg2
import psycopg2.extras
from openai import OpenAI


REPO_ROOT = Path("/mmfs1/gscratch/amath/simku22/TheoremSearch")
MINIMAL_TEMPLATE_PATH = REPO_ROOT / "pipeline/generate_slogans/prompts/minimal.j2"
PROMPT_NAME = "minimal"
MODEL_NAME = "qwen3-235b"
PROVIDER_MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507"
TEMPERATURE = 0.3
MAX_TOKENS = 300


def load_env() -> dict:
    env = {}
    with open(REPO_ROOT / ".env") as f:
        for line in f:
            if line.strip() and not line.startswith("#") and "=" in line:
                k, _, v = line.strip().partition("=")
                env[k] = v.strip("'\"")
    return env


def db_connect(env: dict) -> psycopg2.extensions.connection:
    sm = boto3.client("secretsmanager", region_name=env["AWS_REGION"],
                      aws_access_key_id=env["AWS_ACCESS_KEY_ID"],
                      aws_secret_access_key=env["AWS_SECRET_ACCESS_KEY"])
    secret = json.loads(sm.get_secret_value(SecretId=env["RDS_SECRET_ARN"])["SecretString"])
    host = os.environ.get("RDS_HOST", "localhost")
    port = int(os.environ.get("RDS_PORT", "5432"))
    return psycopg2.connect(host=host, port=port, dbname="v2",
        user=secret["username"], password=secret["password"], sslmode="require")


def fetch_work(conn, shard: int, n_shards: int) -> list[tuple]:
    """Return (statement_id, kind, body, decl_name) for v427+v428 statements
    not yet sloganed under minimal/qwen3-235b."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT st.statement_id::text,
                   st.kind,
                   st.body,
                   fm.decl_name
            FROM statement st
            JOIN paper p ON p.paper_id = st.paper_id
            JOIN formal_metadata fm ON fm.statement_id = st.statement_id
            LEFT JOIN slogan existing
              ON existing.statement_id = st.statement_id
             AND existing.prompt_name = %s
             AND existing.model_name = %s
            WHERE p.external_id IN ('Mathlib_v427','Mathlib_v428')
              AND st.formality = 'formal'
              AND fm.decl_name IS NOT NULL
              AND existing.slogan_id IS NULL
              AND (('x' || substr(md5(st.statement_id::text), 1, 8))::bit(32)::int %% %s) = %s
            ORDER BY st.statement_id
        """, (PROMPT_NAME, MODEL_NAME, n_shards, shard))
        return list(cur.fetchall())


def render_minimal_prompt(template: str, kind: str, body: str, decl_name: str) -> str:
    """Mini-render of pipeline/generate_slogans/prompts/minimal.j2 — does the
    one substitution that template uses: statement.kind | title, statement.note
    (we don't have it here so it stays empty), statement.body, and the
    INSUFFICIENT CONTEXT marker. Decl name prepended to body for context."""
    kind_title = (kind or "").capitalize()
    # Prepend decl_name to body so the model knows what concept it's summarising
    body_with_name = f"{decl_name}:\n{(body or '').strip()}" if (body or '').strip() else decl_name
    out = template.replace("{{ statement.kind | title }}", kind_title)
    out = out.replace("{% if statement.note %} ({{ statement.note }}){% endif %}", "")
    out = out.replace("{{ statement.body }}", body_with_name)
    import re
    out = re.sub(r"\{#.*?#\}", "", out, flags=re.DOTALL).strip()
    return out


def call_llm(oai: OpenAI, prompt: str) -> tuple[str, int, int]:
    resp = oai.chat.completions.create(
        model=PROVIDER_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
    )
    text = resp.choices[0].message.content.strip()
    return text, resp.usage.prompt_tokens, resp.usage.completion_tokens


def process_one(oai: OpenAI, template: str, row: tuple) -> dict | None:
    sid, kind, body, decl_name = row
    try:
        prompt = render_minimal_prompt(template, kind, body, decl_name)
        text, in_tok, out_tok = call_llm(oai, prompt)
        insufficient = text.startswith("INSUFFICIENT CONTEXT:")
        return {
            "statement_id": sid, "slogan": text,
            "in_tokens": in_tok, "out_tokens": out_tok,
            "insufficient_context": insufficient,
        }
    except Exception as e:
        print(f"  err sid={sid[:8]}.. {type(e).__name__}: {e}", file=sys.stderr)
        return None


def batch_insert(conn, rows: list[dict]) -> int:
    if not rows: return 0
    payload = [
        (r["statement_id"], PROMPT_NAME, MODEL_NAME, r["slogan"],
         r["in_tokens"], r["out_tokens"], r["insufficient_context"])
        for r in rows
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO slogan (statement_id, prompt_name, model_name, slogan, "
            "in_tokens, out_tokens, insufficient_context, created_at) "
            "VALUES %s ON CONFLICT (statement_id, prompt_name, model_name) DO NOTHING",
            payload,
            template="(%s::uuid, %s, %s, %s, %s, %s, %s, NOW())",
            page_size=100,
        )
    conn.commit()
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--n-shards", type=int, default=1)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    env = load_env()
    conn = db_connect(env)
    oai = OpenAI(base_url="https://api.studio.nebius.ai/v1/", api_key=env["NEBIUS_API_KEY"])
    template = MINIMAL_TEMPLATE_PATH.read_text()

    t0 = time.time()
    work = fetch_work(conn, args.shard, args.n_shards)
    print(f"[shard {args.shard}/{args.n_shards}] {len(work)} to slogan "
          f"({time.time()-t0:.1f}s fetch)", file=sys.stderr)
    if args.limit: work = work[: args.limit]
    if not work:
        print(f"[shard {args.shard}] nothing to do", file=sys.stderr); return

    t_run = time.time()
    inserted = 0
    insufficient = 0
    total_in = 0
    total_out = 0
    page_size = max(args.workers * 4, 32)
    for start in range(0, len(work), page_size):
        page = work[start : start + page_size]
        results = []
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = [ex.submit(process_one, oai, template, row) for row in page]
            for fut in as_completed(futures):
                r = fut.result()
                if r:
                    results.append(r)
                    total_in += r["in_tokens"]
                    total_out += r["out_tokens"]
                    if r["insufficient_context"]:
                        insufficient += 1
        n = batch_insert(conn, results)
        inserted += n
        elapsed = time.time() - t_run
        rate = inserted / max(1, elapsed)
        eta = (len(work) - inserted) / max(1, rate)
        print(f"[shard {args.shard}] {inserted}/{len(work)} ({rate:.1f}/s, "
              f"eta {eta:.0f}s) insuff={insufficient}",
              file=sys.stderr, flush=True)
    print(f"[shard {args.shard}] DONE inserted={inserted} insuff={insufficient} "
          f"elapsed={time.time()-t_run:.0f}s in_tok={total_in:,} out_tok={total_out:,}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
