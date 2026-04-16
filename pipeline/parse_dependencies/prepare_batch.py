"""
Phase 1: Generate an OpenAI-compatible JSONL batch file for LLM dependency inference.

The custom_id in each request is the paper's arxiv_id so Phase 2 can re-derive
all state from the DB using only that key.

Run:
    python -m pipeline.parse_dependencies.prepare_batch --type inter -o inter.jsonl
    python -m pipeline.parse_dependencies.prepare_batch --type intra -o intra.jsonl
"""

import json
from argparse import ArgumentParser
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from jinja2 import Environment, FileSystemLoader
from tqdm import tqdm

from rds.utils.connect import get_rds_connection
from rds.utils.query import build_query, get_query_count
from rds.utils.paginate import paginate_query
from ..printing import print_script_header

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_jinja_env = Environment(loader=FileSystemLoader(_PROMPTS_DIR), keep_trailing_newline=True)

_FIELD_MAX_CHARS = 1000


def _render(template_name: str) -> str:
    return _jinja_env.get_template(template_name).render()


def _truncate(text: Optional[str]) -> Optional[str]:
    if text and len(text) > _FIELD_MAX_CHARS:
        return text[:_FIELD_MAX_CHARS] + "…"
    return text


def _make_stmt_items(statements: List[Dict]) -> List[dict]:
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
            val = _truncate(s.get(field))
            if val:
                item[field] = val
        items.append(item)
    return items


def _make_batch_entry(arxiv_id: str, user_content: str, model: str, system_prompt: str, max_tokens: int) -> dict:
    return {
        "custom_id": arxiv_id,
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_content},
            ],
            "temperature": 0,
            "max_tokens": max_tokens,
        },
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

    user_content = json.dumps(
        {"bibliography": bib_for_llm, "statements": _make_stmt_items(statements)},
        ensure_ascii=False,
    )
    return _make_batch_entry(arxiv_id, user_content, model, system_prompt, max_tokens=8192)


def _build_intra_request(
    arxiv_id: str,
    statements: List[Dict],
    model: str,
    system_prompt: str,
) -> Optional[dict]:
    if len(statements) < 2:
        return None

    user_content = json.dumps(_make_stmt_items(statements), ensure_ascii=False)
    return _make_batch_entry(arxiv_id, user_content, model, system_prompt, max_tokens=4096)


# ------------------------------------------------------------------ #
# Main                                                                #
# ------------------------------------------------------------------ #

def prepare_batch(
    dep_type: str,
    output: Path,
    model: str,
    overwrite: bool,
    batch_size: int,
    condition: Optional[str],
    condition_params: List[str],
    shard: int,
    n_shards: int,
    sample: int = -1,
):
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
            # Overwrite guards (mirror the online pipeline)
            {
                "if": not overwrite and is_inter,
                "condition": """
                    NOT EXISTS (
                        SELECT 1 FROM informal_dependency d
                        INNER JOIN statement s ON s.statement_id = d.src_id
                        WHERE s.paper_id = paper.paper_id
                          AND d.cite_key IS NOT NULL
                    )
                """,
            },
            {
                "if": not overwrite and not is_inter,
                "condition": """
                    NOT EXISTS (
                        SELECT 1 FROM informal_dependency d
                        INNER JOIN statement s ON s.statement_id = d.src_id
                        WHERE s.paper_id = paper.paper_id
                          AND d.cite_key IS NULL
                    )
                """,
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
    skipped = written = 0

    with (
        output.open("w", encoding="utf-8") as f_out,
        tqdm(total=count, dynamic_ncols=True, unit=" papers", desc="Preparing") as pbar,
    ):
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
                    req = _build_inter_request(arxiv_id, bibs.get(arxiv_id, {}), stmts, model, system_prompt)
                else:
                    req = _build_intra_request(arxiv_id, stmts, model, system_prompt)

                if req is None:
                    skipped += 1
                else:
                    f_out.write(json.dumps(req, ensure_ascii=False) + "\n")
                    written += 1

            pbar.update(len(papers))
            pbar.set_postfix({"written": written, "skipped": skipped})

    print(f"\nDone. {written} requests written to {output}, {skipped} skipped.")


if __name__ == "__main__":
    arg_parser = ArgumentParser(
        description="Generate a JSONL batch file for LLM dependency inference."
    )

    arg_parser.add_argument(
        "--type",
        choices=["inter", "intra"],
        required=True,
        dest="dep_type",
        help="Dependency type: inter (cross-paper citations) or intra (within-paper references).",
    )
    arg_parser.add_argument(
        "-o", "--output",
        type=Path,
        required=True,
        help="Output .jsonl file path.",
    )
    arg_parser.add_argument(
        "--model",
        type=str,
        default="Qwen/Qwen3-235B-A22B-Instruct-2507",
        help="Model ID to embed in each batch request.",
    )
    arg_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Include papers that already have dependency rows of the given type.",
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

    args = arg_parser.parse_args()

    if args.condition and len(args.condition) >= 2:
        condition, *condition_params = args.condition
    else:
        condition        = args.condition[0] if args.condition else None
        condition_params = []

    print_script_header(
        action=f"Preparing {args.dep_type}paper batch",
        params={
            "output":       args.output,
            "model":        args.model,
            "overwrite":    args.overwrite,
            "batch size":   args.batch_size,
            "condition?":   condition,
            "params?":      condition_params,
            "shard":        f"{args.shard}/{args.n_shards}" if args.n_shards > 1 else "off",
            **({"sample": args.sample} if args.sample > 0 else {}),
        },
    )

    prepare_batch(
        dep_type=args.dep_type,
        output=args.output,
        model=args.model,
        overwrite=args.overwrite,
        batch_size=args.batch_size,
        condition=condition,
        condition_params=condition_params,
        shard=args.shard,
        n_shards=args.n_shards,
        sample=args.sample,
    )
