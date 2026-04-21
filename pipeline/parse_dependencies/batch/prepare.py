"""
Phase 1: Generate an OpenAI-compatible JSONL batch file for LLM dependency inference.

The custom_id in each request is the paper's arxiv_id so Phase 2 can re-derive
all state from the DB using only that key.

Run:
    python -m pipeline.parse_dependencies.batch.prepare --type inter -o inter.jsonl
    python -m pipeline.parse_dependencies.batch.prepare --type intra -o intra.jsonl
"""

import json
import tempfile
import yaml
from argparse import ArgumentParser
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Union

from jinja2 import Environment, FileSystemLoader
from tqdm import tqdm

from rds.utils.connect import get_rds_connection
from rds.utils.query import build_query, get_query_count
from rds.utils.paginate import paginate_query
import boto3

from ...printing import print_script_header


_S3_BUCKET = "dependency-graph-bucket"
_S3_FOLDERS = {"inter": "inter_llm_batches", "intra": "intra_llm_batches"}


def _default_output(dep_type: str) -> str:
    return f"s3://{_S3_BUCKET}/{_S3_FOLDERS[dep_type]}/input/"


def _parse_s3_uri(uri: str):
    without_scheme = uri[len("s3://"):]
    bucket, _, key = without_scheme.partition("/")
    return bucket, key


def _indexed_output(output_str: str, index: int) -> str:
    if output_str.endswith("/"):
        return f"{output_str}{index:03d}.jsonl"
    if output_str.startswith("s3://"):
        base, _, name = output_str.rpartition("/")
        stem, dot, ext = name.rpartition(".")
        return f"{base}/{stem}_{index:04d}.{ext}" if dot else f"{base}/{name}_{index:04d}"
    p = Path(output_str)
    return str(p.parent / f"{p.stem}_{index:04d}{p.suffix}")


def _clear_s3_folder(prefix: str):
    """Delete all objects under an S3 prefix (e.g. 's3://bucket/folder/')."""
    bucket, key = _parse_s3_uri(prefix)
    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    to_delete = []
    for page in paginator.paginate(Bucket=bucket, Prefix=key):
        for obj in page.get("Contents", []):
            to_delete.append({"Key": obj["Key"]})
    if to_delete:
        s3.delete_objects(Bucket=bucket, Delete={"Objects": to_delete})


def _list_s3_files(prefix: str) -> List[str]:
    """Return sorted list of S3 URIs under prefix."""
    bucket, key = _parse_s3_uri(prefix)
    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    uris = []
    for page in paginator.paginate(Bucket=bucket, Prefix=key):
        for obj in page.get("Contents", []):
            uris.append(f"s3://{bucket}/{obj['Key']}")
    return sorted(uris)


def _open_output(dest: str):
    """Open dest for writing. Returns (local_path, file_handle)."""
    if dest.startswith("s3://"):
        tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        tmp.close()
        local = Path(tmp.name)
    else:
        local = Path(dest)
    return local, local.open("w", encoding="utf-8")


def _finalize_output(f_out, local_path: Path, dest: str):
    f_out.close()
    if dest.startswith("s3://"):
        bucket, key = _parse_s3_uri(dest)
        boto3.client("s3").upload_file(str(local_path), bucket, key)
        local_path.unlink()

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_jinja_env = Environment(loader=FileSystemLoader(_PROMPTS_DIR), keep_trailing_newline=True)

def _render(template_name: str) -> str:
    return _jinja_env.get_template(template_name).render()


def _truncate(text: Optional[str], max_chars: int, tail: bool = False) -> Optional[str]:
    if text and len(text) > max_chars:
        return ("…" + text[-max_chars:]) if tail else (text[:max_chars] + "…")
    return text


def _make_stmt_items(statements: List[Dict], max_chars: int) -> List[dict]:
    """Build the shared stmt_items list used by both request builders."""
    used_ids: Dict[str, int] = {}
    items = []
    for i, s in enumerate(statements):
        base_id = s.get("ref") or f"{s['kind'].capitalize()} {i + 1}"
        if base_id in used_ids:
            used_ids[base_id] += 1
            sid = f"{base_id} ({used_ids[base_id]})"
        else:
            used_ids[base_id] = 0
            sid = base_id

        item: dict = {"id": sid, "kind": s["kind"]}
        for field in ("note", "body", "proof", "pre_context", "post_context"):
            val = _truncate(s.get(field), max_chars, tail=(field == "pre_context"))
            if val:
                item[field] = val
        items.append(item)
    return items


def _make_batch_entry(
    arxiv_id: str,
    user_content: str,
    model: str,
    system_prompt: str,
    max_tokens: int,
    budget_tokens: Optional[int],
) -> dict:
    body: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_content},
        ],
        "max_tokens": max_tokens,
    }
    if budget_tokens is not None:
        body["chat_template_kwargs"] = {"enable_thinking": True, "thinking_budget": budget_tokens}
    return {
        "custom_id": arxiv_id,
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": body,
    }


# ------------------------------------------------------------------ #
# Per-type request builders                                           #
# ------------------------------------------------------------------ #

def _build_inter_request(
    arxiv_id: str,
    bib: Dict[str, Dict],
    statements: List[Dict],
    model: str,
    system_prompt: str,
    max_tokens: int,
    budget_tokens: Optional[int],
    max_chars: int = 128,
) -> Optional[dict]:
    if not statements or not bib:
        return None

    all_text = " ".join(
        (s.get(f) or "")
        for s in statements
        for f in ("body", "proof", "note", "pre_context", "post_context")
    )
    bib_for_llm = {
        k: {f: v[f] for f in ("title", "arxiv_id") if v.get(f)}
        for k, v in bib.items()
        if k in all_text
    }
    if not bib_for_llm:
        return None

    user_content = yaml.dump(
        {"bibliography": bib_for_llm, "statements": _make_stmt_items(statements, max_chars)},
        allow_unicode=True,
        sort_keys=False,
    )
    return _make_batch_entry(arxiv_id, user_content, model, system_prompt, max_tokens, budget_tokens)


def _build_intra_request(
    arxiv_id: str,
    statements: List[Dict],
    model: str,
    system_prompt: str,
    max_tokens: int,
    budget_tokens: Optional[int],
    max_chars: int = 128,
) -> Optional[dict]:
    if len(statements) < 2:
        return None

    user_content = yaml.dump(_make_stmt_items(statements, max_chars), allow_unicode=True, sort_keys=False)
    return _make_batch_entry(arxiv_id, user_content, model, system_prompt, max_tokens, budget_tokens)


# ------------------------------------------------------------------ #
# Main                                                                #
# ------------------------------------------------------------------ #

def prepare_batch(
    dep_type: str,
    output: Union[str, Path],
    model: str,
    max_tokens: int,
    budget_tokens: Optional[int],
    max_chars: int,
    batch_size: int,
    condition: Optional[str],
    condition_params: List[str],
    shard: int,
    n_shards: int,
    sample: int = -1,
    rows_per_file: int = -1,
):
    output_str = str(output)
    is_dir = output_str.endswith("/")
    splitting = rows_per_file > 0

    if is_dir and output_str.startswith("s3://"):
        print(f"Clearing {output_str} ...")
        _clear_s3_folder(output_str)

    conn = get_rds_connection("v2")

    is_inter = dep_type == "inter"
    system_prompt = _render("interpaper_llm_system.j2" if is_inter else "intrapaper_llm_system.j2")

    needs_apm = is_inter or (condition and "apm." in condition)
    needs_aps = condition and "aps." in condition

    query, params = build_query(
        sample=sample,
        base_query=(
            "SELECT paper.paper_id, paper.external_id"
            " FROM paper"
            + (" INNER JOIN arxiv_paper_metadata AS apm ON apm.arxiv_id = paper.external_id" if needs_apm else "")
            + (" LEFT JOIN arxiv_parse_status AS aps ON aps.arxiv_id = paper.external_id" if needs_aps else "")
        ),
        where_clauses=[
            {
                "if": True,
                "condition": "paper.kind = 'paper'",
            },
            {
                "if": True,
                "condition": "EXISTS (SELECT 1 FROM statement s WHERE s.paper_id = paper.paper_id)",
            },
            # Inter-only: restrict to parsed bibtex bibliographies
            {
                "if": is_inter,
                "condition": "apm.bibtex = TRUE AND apm.bibliography IS NOT NULL",
            },
            {
                "if": condition,
                "condition": condition,
                "params": condition_params,
            },
            {
                "if": n_shards > 1,
                "condition": "hashtext(paper.paper_id::text) %% %s = %s",
                "params": [n_shards, shard],
            },
        ],
    )

    count = get_query_count(conn, query, params)
    skipped = written = total_chars = 0
    file_index = 0
    rows_in_file = 0
    current_dest = _indexed_output(output_str, file_index) if (splitting or is_dir) else output_str
    current_local, f_out = _open_output(current_dest)

    with tqdm(total=count, dynamic_ncols=True, unit=" papers", desc="Preparing") as pbar:
        for papers in paginate_query(
            conn,
            base_query=query,
            base_params=params,
            order_by="paper_id",
            page_size=batch_size,
        ):
            paper_ids = [p["paper_id"]    for p in papers]
            arxiv_ids = [p["external_id"] for p in papers]

            bibs: Dict[str, dict] = {}
            if is_inter:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT arxiv_id, bibliography"
                        " FROM arxiv_paper_metadata"
                        " WHERE arxiv_id = ANY(%s)",
                        (arxiv_ids,),
                    )
                    bibs = {row[0]: (row[1] or {}) for row in cur.fetchall()}

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT s.statement_id, s.paper_id, s.kind, s.body, s.proof,
                           im.ref, im.note, im.pre_context, im.post_context
                    FROM statement s
                    INNER JOIN informal_metadata im ON im.statement_id = s.statement_id
                    WHERE s.paper_id = ANY(%s::uuid[])
                    ORDER BY s.paper_id, im.ordinal
                    """,
                    (paper_ids,),
                )
                stmts_by_paper: Dict[str, list] = defaultdict(list)
                for row in cur.fetchall():
                    stmt = dict(zip(
                        ["statement_id", "paper_id", "kind", "body", "proof",
                         "ref", "note", "pre_context", "post_context"],
                        row,
                    ))
                    stmts_by_paper[stmt["paper_id"]].append(stmt)

            for paper in papers:
                arxiv_id = paper["external_id"]
                stmts    = stmts_by_paper.get(paper["paper_id"], [])

                if is_inter:
                    req = _build_inter_request(arxiv_id, bibs.get(arxiv_id, {}), stmts, model, system_prompt, max_tokens, budget_tokens, max_chars)
                else:
                    req = _build_intra_request(arxiv_id, stmts, model, system_prompt, max_tokens, budget_tokens, max_chars)

                if req is None:
                    skipped += 1
                else:
                    if splitting and rows_in_file >= rows_per_file:
                        _finalize_output(f_out, current_local, current_dest)
                        file_index += 1
                        rows_in_file = 0
                        current_dest = _indexed_output(output_str, file_index)
                        current_local, f_out = _open_output(current_dest)
                    f_out.write(json.dumps(req, ensure_ascii=False) + "\n")
                    total_chars += sum(len(m["content"]) for m in req["body"]["messages"])
                    written += 1
                    rows_in_file += 1

            pbar.update(len(papers))
            pbar.set_postfix({"written": written, "skipped": skipped})

    _finalize_output(f_out, current_local, current_dest)
    n_files = file_index + 1
    if is_dir:
        dest_display = output_str
    elif splitting:
        dest_display = _indexed_output(output_str, 0).replace("_0000", "_*")
    else:
        dest_display = current_dest
    est_tokens = total_chars // 4
    print(
        f"\nDone. {written} requests written to {n_files} file(s) ({dest_display}), {skipped} skipped."
        f"\n  Estimated input tokens: ~{est_tokens:,} (~{total_chars:,} chars ÷ 4)"
    )


if __name__ == "__main__":
    arg_parser = ArgumentParser(
        description="Generate a JSONL batch file for LLM dependency inference."
    )

    arg_parser.add_argument(
        "--inter",
        action="store_true",
        help="Prepare inter-paper batch only.",
    )
    arg_parser.add_argument(
        "--intra",
        action="store_true",
        help="Prepare intra-paper batch only.",
    )
    arg_parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Output path: local file or s3://bucket/key. Defaults to the appropriate S3 folder. Cannot be used when preparing both types.",
    )
    arg_parser.add_argument(
        "--model",
        type=str,
        default="Qwen/Qwen3-Next-80B-A3B-Thinking-fast",
        help="Model ID to embed in each batch request.",
    )
    arg_parser.add_argument(
        "--max-tokens",
        type=int,
        default=8192,
        dest="max_tokens",
        help="Maximum output tokens per request (default: 8192).",
    )
    arg_parser.add_argument(
        "--budget-tokens",
        type=int,
        default=3000,
        dest="budget_tokens",
        help="Thinking budget tokens for reasoning models; 0 to disable (default: 3000).",
    )
    arg_parser.add_argument(
        "--max-chars",
        type=int,
        default=128,
        dest="max_chars",
        help="Max characters per statement field sent to the LLM (default: 128).",
    )
    arg_parser.add_argument(
        "-b", "--batch-size",
        type=int,
        default=256,
        dest="batch_size",
        help="Papers fetched from DB per iteration (default: 256).",
    )
    arg_parser.add_argument(
        "-c", "--condition",
        type=str,
        nargs="+",
        metavar=("SQL", "PARAM"),
        help="SQL WHERE condition to filter papers, followed by any bind parameters.",
    )
    arg_parser.add_argument(
        "--shard",
        type=int,
        default=0,
    )
    arg_parser.add_argument(
        "--n-shards",
        type=int,
        default=1,
        dest="n_shards",
    )
    arg_parser.add_argument(
        "--sample",
        type=int,
        default=-1,
        help="Randomly sample this many papers (for testing). Uses TABLESAMPLE BERNOULLI.",
    )
    arg_parser.add_argument(
        "--rows-per-file",
        type=int,
        default=-1,
        dest="rows_per_file",
        help="Split output into files of at most this many rows. Output path gets _0000, _0001, … suffixes.",
    )

    args = arg_parser.parse_args()

    dep_types = [t for t, flag in [("inter", args.inter), ("intra", args.intra)] if flag] or ["inter", "intra"]

    if args.output is not None and len(dep_types) > 1:
        arg_parser.error("-o/--output cannot be used when preparing both types.")

    if args.condition and len(args.condition) >= 2:
        condition, *condition_params = args.condition
    else:
        condition        = args.condition[0] if args.condition else None
        condition_params = []

    for dep_type in dep_types:
        output = args.output if args.output is not None else _default_output(dep_type)

        budget_tokens = args.budget_tokens if args.budget_tokens > 0 else None

        print_script_header(
            action=f"Preparing {dep_type}paper batch",
            params={
                "output":         output,
                "model":          args.model,
                "max tokens":     args.max_tokens,
                "budget tokens":  budget_tokens,
                "max chars":      args.max_chars,
                "batch size":     args.batch_size,
                "condition?":     condition,
                "params?":        condition_params,
                "shard":          f"{args.shard}/{args.n_shards}" if args.n_shards > 1 else "off",
                "sample?":        args.sample if args.sample > 0 else None,
                "rows/file?":     args.rows_per_file if args.rows_per_file > 0 else None,
            },
        )

        prepare_batch(
            dep_type=dep_type,
            output=output,
            model=args.model,
            max_tokens=args.max_tokens,
            budget_tokens=budget_tokens,
            max_chars=args.max_chars,
            batch_size=args.batch_size,
            condition=condition,
            condition_params=condition_params,
            shard=args.shard,
            n_shards=args.n_shards,
            sample=args.sample,
            rows_per_file=args.rows_per_file,
        )
