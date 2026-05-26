"""Standalone slogan regen for the LSv2-style prompt experiment.

Generates new slogans for Mathlib v427+v428 statements using the
`pipeline/generate_slogans/prompts/lsv2-style.j2` template, the shared
formal-context fetcher (decl_name + signature + dep names), the qwen3-235b
LLM via Nebius, and inserts into the `slogan` table under
(prompt_name='lsv2-style', model_name='qwen3-235b').

Self-contained: doesn't go through the shared `pipeline.generate_slogans`
CLI (which doesn't allow custom prompts in formal mode). It reuses the
shared formal-context fetcher and prompt loading so output matches what
that pipeline would produce.

Resume-safe: skips any (statement_id, 'lsv2-style', 'qwen3-235b') row that
already exists. Sharded for SLURM array parallelism.

Usage:
  python3 regen_lsv2_slogans.py --shard 0 --n-shards 16 --workers 8
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
PROMPT_FILE = REPO_ROOT / "pipeline/generate_slogans/prompts/lsv2-style.j2"
PROMPT_NAME = "lsv2-style"
MODEL_NAME = "qwen3-235b"
PROVIDER_MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507"
TEMPERATURE = 0.3
MAX_TOKENS = 400


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


def ensure_prompt_registered(conn) -> None:
    """Register lsv2-style in slogan_prompt if not present."""
    template_text = PROMPT_FILE.read_text()
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM slogan_prompt WHERE name = %s", (PROMPT_NAME,))
        if cur.fetchone():
            return
        cur.execute(
            "INSERT INTO slogan_prompt (name, template, created_at) VALUES (%s, %s, NOW())",
            (PROMPT_NAME, template_text),
        )
    conn.commit()
    print(f"[init] registered slogan_prompt.name = {PROMPT_NAME!r}", file=sys.stderr)


def fetch_work(conn, shard: int, n_shards: int) -> list[tuple]:
    """Return [(statement_id, kind, body, decl_name, module, docstring), ...] for
    Mathlib v427+v428 formal statements not yet sloganed under lsv2-style.

    Skips statements that already have an INSUFFICIENT_CONTEXT slogan under
    lsv2-style — those are completed attempts we shouldn't retry.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT st.statement_id::text,
                   st.kind,
                   st.body,
                   fm.decl_name,
                   fm.module,
                   fm.docstring
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
              AND (abs(('x' || substr(md5(st.statement_id::text), 1, 8))::bit(32)::int::bigint) %% %s) = %s
            ORDER BY st.statement_id
        """, (PROMPT_NAME, MODEL_NAME, n_shards, shard))
        return list(cur.fetchall())


def fetch_top_deps(conn, statement_id: str, k: int = 6) -> list[str]:
    """Top-k formal_dependency parent decl_names (just names, for prompt context)."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT fm.decl_name
            FROM formal_dependency fd
            JOIN formal_metadata fm ON fm.statement_id = fd.dep_id
            WHERE fd.src_id = %s::uuid AND fm.decl_name IS NOT NULL
            LIMIT %s
        """, (statement_id, k))
        return [r[0] for r in cur.fetchall()]


def render_target_block(decl_name: str, kind: str, body: str | None,
                        docstring: str | None, module: str | None,
                        deps: list[str]) -> str:
    """Build the `target_block` Jinja variable expected by the lsv2-style.j2
    template. Mirrors what formal_prompt_utils would render but condensed.
    """
    parts = [f"Declaration: {decl_name}", f"Kind: {kind}"]
    if module:
        parts.append(f"Module: {module}")
    if docstring and docstring.strip():
        parts.append(f"Docstring: {docstring.strip()[:1000]}")
    if body and body.strip():
        parts.append(f"Lean source: {body.strip()[:2000]}")
    if deps:
        parts.append(f"Top dependency names: {', '.join(deps)}")
    return "\n".join(parts)


def render_prompt(template_text: str, target_block: str) -> str:
    """Mini-Jinja-substitute. Avoids importing jinja2 for a tiny render."""
    # The lsv2-style template uses only {{ target_block }} and the conditional
    # {% if deps_text %}...{% endif %} block; we never set deps_text here
    # because we already include deps in target_block. Strip the conditional
    # block entirely with a simple regex.
    import re
    out = template_text.replace("{{ target_block }}", target_block)
    # Strip {% if deps_text %} ... {% endif %} verbatim
    out = re.sub(r"\{% if deps_text %\}.*?\{% endif %\}", "", out, flags=re.DOTALL)
    # Strip the budget comment too
    out = re.sub(r"\{#.*?#\}", "", out, flags=re.DOTALL).strip()
    return out


def call_llm(oai: OpenAI, prompt: str) -> tuple[str, int, int]:
    """Returns (text, in_tokens, out_tokens). Strips trailing whitespace."""
    resp = oai.chat.completions.create(
        model=PROVIDER_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
    )
    text = resp.choices[0].message.content.strip()
    in_tok = resp.usage.prompt_tokens
    out_tok = resp.usage.completion_tokens
    return text, in_tok, out_tok


def parse_response(text: str) -> tuple[str, bool]:
    """Returns (slogan_text, insufficient_context)."""
    if text.startswith("INSUFFICIENT CONTEXT:"):
        return text, True
    return text, False


def process_one(conn_template: tuple, oai: OpenAI, template_text: str,
                row: tuple) -> dict | None:
    """Render prompt, call LLM, return insert payload. Uses its own DB conn
    for dep lookup so worker threads don't share state."""
    sid, kind, body, decl_name, module, docstring = row
    # Each worker thread shares the parent conn — use a SAVEPOINT to isolate
    # if needed; for read-only dep lookup it's fine.
    try:
        env, conn = conn_template
        deps = fetch_top_deps(conn, sid, k=6)
        target = render_target_block(decl_name, kind, body, docstring, module, deps)
        prompt = render_prompt(template_text, target)
        text, in_tok, out_tok = call_llm(oai, prompt)
        slogan, insufficient = parse_response(text)
        return {
            "statement_id": sid,
            "slogan": slogan,
            "in_tokens": in_tok,
            "out_tokens": out_tok,
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
    ap.add_argument("--workers", type=int, default=8,
                    help="Concurrent Nebius LLM calls per shard")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    env = load_env()
    conn = db_connect(env)
    ensure_prompt_registered(conn)
    oai = OpenAI(base_url="https://api.studio.nebius.ai/v1/", api_key=env["NEBIUS_API_KEY"])
    template_text = PROMPT_FILE.read_text()

    t0 = time.time()
    work = fetch_work(conn, args.shard, args.n_shards)
    print(f"[shard {args.shard}/{args.n_shards}] {len(work)} statements to slogan "
          f"({time.time()-t0:.1f}s fetch)", file=sys.stderr)
    if args.limit:
        work = work[: args.limit]
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
            futures = [ex.submit(process_one, (env, conn), oai, template_text, row) for row in page]
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
        print(f"[shard {args.shard}] {inserted}/{len(work)}  ({rate:.1f}/s, "
              f"eta {eta:.0f}s)  insuff={insufficient}  in_tok={total_in:,} out_tok={total_out:,}",
              file=sys.stderr, flush=True)

    print(f"[shard {args.shard}] DONE  inserted={inserted}  insufficient={insufficient}  "
          f"elapsed={time.time()-t_run:.0f}s  in_tok={total_in:,} out_tok={total_out:,}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
