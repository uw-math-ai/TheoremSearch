import sys
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import List, Optional

from tqdm import tqdm

from rds.utils.connect import get_rds_connection
from rds.utils.query import build_query
from rds.utils.upsert import upsert_rows
from ..printing import print_script_header
from .clients import make_client
from .prompt_utils import (
    load_prompt, load_model_config,
    detect_needed_joins, fetch_contexts, render_prompt,
    register_prompt, register_model,
    condition_joins, parse_slogan_text,
    PROMPTS_DIR,
)
from .formal_prompt_utils import (
    FormalContextSpec, fetch_formal_contexts, _DEFAULT_BUDGET as _FORMAL_DEFAULT_BUDGET,
)

_PROVIDERS = ("nebius", "bedrock")

_BATCH_PHASES = ("prepare", "run", "poll", "upsert")
_DEFAULT_CHAIN = ("minimal", "standard", "comprehensive", "final")

# Selects statements that (a) have at least one insufficient slogan and
# (b) have NO sufficient slogan. Equivalent to the old bool_and(insufficient_context)
# group filter, but written as two EXISTS clauses so each can use an index
# (idx_slogan_insufficient / idx_slogan_sufficient partial indexes).
_INSUFFICIENT_ONLY_SQL = """
    EXISTS (
        SELECT 1 FROM slogan
        WHERE slogan.statement_id = statement.statement_id
          AND slogan.insufficient_context
    )
    AND NOT EXISTS (
        SELECT 1 FROM slogan
        WHERE slogan.statement_id = statement.statement_id
          AND NOT slogan.insufficient_context
    )
"""


def _err(msg: str):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(2)


def generate_slogans(
    prompt_name: str,
    model_name: str,
    condition: Optional[str],
    condition_params: List[str],
    overwrite: bool,
    batch_size: int,
    workers: int,
    shard: int,
    n_shards: int,
    only_insufficient: bool = False,
    test: bool = False,
    mode: str = "informal",
    provider: str = "nebius",
    region: Optional[str] = None,
):
    spec = load_prompt(prompt_name, mode=mode)
    model_config = load_model_config(model_name)

    # Provider validation: bedrock requires the per-entry 'bedrock_model' override.
    # We surface this here (early, with a friendly message) rather than letting
    # make_client raise after register_prompt / register_model have already run.
    if provider == "bedrock" and not model_config.get("bedrock_model"):
        _err(
            f"--provider bedrock requires a 'bedrock_model' field on models.json "
            f"entry '{model_name}'. Add e.g. "
            f"\"bedrock_model\": \"qwen.qwen3-...-v1:0\"."
        )

    is_formal = mode == "formal"
    # Informal templates pick joins by introspection; formal mode uses a
    # fixed fetcher (formal_prompt_utils.fetch_formal_contexts) and a budget.
    joins      = None if is_formal else detect_needed_joins(spec.source)
    formal_ctx = FormalContextSpec(
        prompt_name=prompt_name,
        budget=spec.budget or _FORMAL_DEFAULT_BUDGET,
    ) if is_formal else None

    print_script_header(
        action="Generating slogans",
        params={
            "provider":          provider,
            "region?":           region if provider == "bedrock" else None,
            "mode":              mode,
            "test mode?":        test or None,
            "prompt":            prompt_name,
            "model":             model_name,
            "condition?":        condition,
            "condition params?": condition_params,
            "insufficient only": only_insufficient or None,
            "overwrite":         overwrite,
            "batch size":        batch_size,
            "workers":           workers,
            "shard?":            f"{shard}/{n_shards}" if n_shards > 1 else None,
            "char budget":       formal_ctx.budget if is_formal else None,
        }
    )

    base_query = "SELECT statement.statement_id FROM statement" + condition_joins(condition)
    # Formal mode auto-restricts to formal statements.
    formality_clause = "statement.formality = 'formal'" if is_formal else None

    conn = get_rds_connection("v2")

    if test:
        test_query, test_params = build_query(
            base_query=base_query,
            where_clauses=[
                {
                    "if": is_formal,
                    "condition": formality_clause or "",
                    "params": [],
                },
                {
                    "if": bool(condition),
                    "condition": condition or "",
                    "params": condition_params,
                },
                {
                    "if": only_insufficient,
                    "condition": _INSUFFICIENT_ONLY_SQL,
                    "params": [],
                },
                {
                    "if": n_shards > 1,
                    "condition": "ABS(hashtext(statement.statement_id::text)) %% %s = %s",
                    "params": [n_shards, shard],
                },
            ],
        )
        page = next(iter(paginate_query(conn, base_query=test_query, base_params=test_params, order_by="statement_id", page_size=1)), [])
        if not page:
            print("No matching statements found.")
            return
        sid = str(page[0]["statement_id"])
        if is_formal:
            contexts = fetch_formal_contexts(conn, [sid], formal_ctx)
        else:
            contexts = fetch_contexts(conn, [sid], joins)
        if sid not in contexts:
            print(f"Could not fetch context for statement {sid}.")
            return
        rendered = render_prompt(spec.template, contexts[sid])
        example_path = PROMPTS_DIR / f"{prompt_name}.example.txt"
        example_path.write_text(rendered + "\n")
        print(f"Written to {example_path}\n")
        print(rendered)
        return

    register_prompt(conn, spec)
    register_model(conn, model_name, model_config)

    client = make_client(provider, model_config, region=region)

    query, params = build_query(
        base_query=base_query,
        where_clauses=[
            {
                "if": is_formal,
                "condition": formality_clause or "",
                "params": [],
            },
            {
                "if": not overwrite,
                "condition": """
                    NOT EXISTS (
                        SELECT 1 FROM slogan
                        WHERE slogan.statement_id = statement.statement_id
                          AND slogan.prompt_name = %s
                          AND slogan.model_name = %s
                    )
                """,
                "params": [spec.name, model_name],
            },
            {
                "if": bool(condition),
                "condition": condition or "",
                "params": condition_params,
            },
            {
                "if": only_insufficient,
                "condition": _INSUFFICIENT_ONLY_SQL,
                "params": [],
            },
            {
                "if": n_shards > 1,
                "condition": "ABS(hashtext(statement.statement_id::text)) %% %s = %s",
                "params": [n_shards, shard],
            },
        ],
    )

    # One-shot candidate fetch. Replaces (a) get_query_count's upfront full
    # filter scan + (b) paginate_query's per-page re-execution of the same
    # NOT EXISTS / EXISTS chain — both of which made every page pay for the
    # whole filter on tables with millions of slogans.
    print("Selecting statement_ids to process ...", flush=True)
    with conn.cursor() as cur:
        cur.execute(f"{query} ORDER BY statement.statement_id", params)
        all_ids = [str(r[0]) for r in cur.fetchall()]
    total = len(all_ids)
    print(f"  {total:,} statement(s) to process", flush=True)
    if total == 0:
        return

    status_counts = {"success": 0, "failed": 0}

    def call_llm(statement_id: str, prompt_text: str) -> dict:
        text, usage = client.complete(
            prompt_text,
            temperature=model_config.get("temperature", 0.7),
            max_tokens=model_config.get("max_tokens", 512),
        )
        slogan, insufficient = parse_slogan_text(text)
        return {
            "statement_id":         statement_id,
            "prompt_name":          spec.name,
            "model_name":           model_name,
            "slogan":               slogan,
            "insufficient_context": insufficient,
            "in_tokens":            usage.get("prompt_tokens"),
            "out_tokens":           usage.get("completion_tokens"),
            "created_at":           datetime.now(timezone.utc),
        }

    cost_per_1m_in  = model_config.get("cost_per_1m_in",  0.0)
    cost_per_1m_out = model_config.get("cost_per_1m_out", 0.0)
    total_in_tokens  = 0
    total_out_tokens = 0

    pbar = tqdm(total=total, dynamic_ncols=True)

    with pbar, ThreadPoolExecutor(max_workers=workers) as ex:
        for start in range(0, total, batch_size):
            statement_ids = all_ids[start:start + batch_size]
            if is_formal:
                contexts = fetch_formal_contexts(conn, statement_ids, formal_ctx)
            else:
                contexts = fetch_contexts(conn, statement_ids, joins)

            fut_to_sid = {}
            for sid in statement_ids:
                if sid not in contexts:
                    status_counts["failed"] += 1
                    pbar.update()
                    continue
                prompt_text = render_prompt(spec.template, contexts[sid])
                fut = ex.submit(call_llm, sid, prompt_text)
                fut_to_sid[fut] = sid

            batch_rows = []
            for fut in as_completed(fut_to_sid):
                try:
                    row = fut.result()
                    batch_rows.append(row)
                    status_counts["success"] += 1
                    total_in_tokens  += row["in_tokens"]  or 0
                    total_out_tokens += row["out_tokens"] or 0
                except Exception as e:
                    status_counts["failed"] += 1
                    print(f"\n[error] {fut_to_sid[fut]}: {e}")
                pbar.update()
                total_done = sum(status_counts.values())
                cost = (
                    total_in_tokens  / 1_000_000 * cost_per_1m_in
                    + total_out_tokens / 1_000_000 * cost_per_1m_out
                )
                pbar.set_postfix({
                    "success": f"{100.0 * status_counts['success'] / total_done:.1f}%",
                    "avg_cost": f"${cost / status_counts['success']:.5f}" if status_counts["success"] else "$0",
                    "cost": f"${cost:.4f}",
                })

            if batch_rows:
                upsert_rows(
                    conn,
                    table="slogan",
                    rows=batch_rows,
                    on_conflict={
                        "with":    ["statement_id", "prompt_name", "model_name"],
                        "replace": ["slogan", "insufficient_context", "in_tokens", "out_tokens"],
                        # created_at intentionally excluded: preserves original creation time
                    },
                )
                conn.commit()


if __name__ == "__main__":
    parser = ArgumentParser(
        description="Generate LLM slogans for mathematical statements."
    )

    parser.add_argument(
        "--formal",
        action="store_true",
        help=(
            "Generate formal slogans: restricts to formality='formal' statements "
            "and uses formal_metadata + ranked formal_dependency edges under a "
            "char budget. The prompt is fixed to 'formal' (prompts/formal.j2); "
            "incompatible with -p/--prompt, --chain, and --batch. Without this "
            "flag, the script runs in informal mode."
        ),
    )
    parser.add_argument(
        "--provider",
        choices=_PROVIDERS,
        default="nebius",
        help=(
            "LLM provider for online mode. nebius (default) uses the Nebius "
            "OpenAI-compatible endpoint via NEBIUS_API_KEY. bedrock uses AWS "
            "Bedrock Converse API via default boto3 credentials (AWS_REGION "
            "/ AWS_DEFAULT_REGION must be set). The chosen --provider must "
            "match the model entry's `provider` field in models.json. "
            "bedrock is online-only — incompatible with --batch."
        ),
    )
    parser.add_argument(
        "--region",
        type=str,
        default=None,
        help=(
            "AWS region for --provider bedrock (e.g. us-west-2). Overrides the "
            "models.json 'region' field and AWS_REGION / AWS_DEFAULT_REGION env "
            "vars. Use to shard Bedrock traffic across regions for more aggregate "
            "throughput. Ignored for non-bedrock providers."
        ),
    )
    parser.add_argument(
        "-p", "--prompt",
        type=str,
        required=False,
        dest="prompt_name",
        help=(
            "Prompt template name (without .j2) under pipeline/generate_slogans/prompts/. "
            "Required unless --chain or --formal is used. In --formal mode the prompt "
            "is always 'formal' and this flag must be omitted."
        ),
    )
    parser.add_argument(
        "--chain",
        nargs="?",
        const=",".join(_DEFAULT_CHAIN),
        default=None,
        metavar="p1,p2,...",
        help=(
            "Run prompts in escalation order. The first prompt runs on all matching statements; "
            "each later prompt only runs on statements whose existing slogans are all marked "
            "insufficient_context. Bare flag uses the default chain: "
            f"{','.join(_DEFAULT_CHAIN)}. Online mode only; incompatible with -p, --batch, --test."
        ),
    )
    parser.add_argument(
        "-c", "--condition",
        type=str,
        nargs="+",
        metavar=("SQL", "PARAM"),
        help=(
            "SQL WHERE condition to filter statements, followed by any bind parameters. "
            "The 'statement' table and (if needed) 'paper' table are in scope. "
            "Example: -c \"paper.external_id = %%s\" 2301.00001"
        ),
    )
    parser.add_argument(
        "-o", "--overwrite",
        action="store_true",
        help="Re-generate slogans for statements that already have one for this prompt.",
    )
    parser.add_argument(
        "--insufficient",
        action="store_true",
        dest="only_insufficient",
        help=(
            "Restrict to statements where every existing slogan is marked "
            "insufficient_context. Works in both online and --batch prepare modes. "
            "Typically combined with --overwrite to retry these statements."
        ),
    )
    parser.add_argument(
        "-b", "--batch-size",
        type=int,
        default=32,
        dest="batch_size",
        help="Statements fetched and processed per iteration. Default: 32.",
    )
    parser.add_argument(
        "-m", "--model",
        type=str,
        required=True,
        dest="model_name",
        help="Short model name from models.json (e.g. 'qwen3-235b').",
    )
    parser.add_argument(
        "-w", "--workers",
        type=int,
        default=4,
        help="Concurrent LLM requests. Default: 4.",
    )
    parser.add_argument(
        "--shard",
        type=int,
        default=0,
        help="0-based shard index for array jobs. Default: 0.",
    )
    parser.add_argument(
        "--n-shards",
        type=int,
        default=1,
        dest="n_shards",
        help="Total number of shards. Default: 1 (no sharding).",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help=(
            "Render the prompt for the first matching statement and write it to "
            "prompts/<prompt>/example.txt. No LLM call or DB write."
        ),
    )
    parser.add_argument(
        "--batch",
        choices=_BATCH_PHASES,
        default=None,
        metavar="PHASE",
        help=(
            f"Run a batch pipeline phase ({', '.join(_BATCH_PHASES)}) instead of online processing."
        ),
    )
    # Batch-prepare / run / upsert passthrough args
    parser.add_argument("-i", "--input", type=str, nargs="+", default=None, dest="batch_input",
                        help="Batch input path(s) (for --batch run/upsert).")
    parser.add_argument("--output", type=str, default=None, dest="batch_output",
                        help="Batch output path (for --batch prepare/run).")
    parser.add_argument("--sample", type=int, default=-1,
                        help="Randomly sample N statements (for --batch prepare, testing).")
    parser.add_argument("--rows-per-file", type=int, default=-1, dest="rows_per_file",
                        help="Split batch output into files of at most N rows.")
    # Batch-poll passthrough flags
    parser.add_argument("--download", action="store_true",
                        help="(--batch poll) Download results for completed batches and remove them from state.")
    parser.add_argument("--all", action="store_true", dest="all_batches",
                        help="(--batch poll) List all batches on the account, not just those in the state file.")
    parser.add_argument("--cancel", action="store_true",
                        help="(--batch poll) Cancel all non-terminal batches.")

    args = parser.parse_args()

    if args.condition and len(args.condition) >= 2:
        condition, *condition_params = args.condition
    else:
        condition = args.condition[0] if args.condition else None
        condition_params = []

    # ── Validate --formal / -p / --chain combinations ────────────────────
    mode = "formal" if args.formal else "informal"

    if args.formal:
        if args.prompt_name:
            _err("--formal fixes the prompt to 'formal'; do not pass -p/--prompt")
        if args.chain is not None:
            _err("--formal is single-prompt; --chain is not supported")
        if args.batch is not None:
            _err("--formal does not yet support --batch (online mode only)")
        args.prompt_name = "formal"
        chain = None
    elif args.chain is not None:
        if args.prompt_name:
            _err("--chain cannot be combined with -p/--prompt")
        if args.batch is not None:
            _err("--chain is online-mode only; remove --batch")
        if args.test:
            _err("--chain cannot be combined with --test")
        chain = [s.strip() for s in args.chain.split(",") if s.strip()]
        if not chain:
            _err("--chain requires at least one prompt name")
    elif not args.prompt_name:
        _err("either -p/--prompt, --chain, or --formal is required")
    else:
        chain = None

    if args.provider != "nebius" and args.batch is not None:
        _err(f"--provider {args.provider} is online-only; remove --batch")

    if args.region and args.provider != "bedrock":
        _err("--region only applies to --provider bedrock")

    # ── Chain mode ───────────────────────────────────────────────────────
    if chain is not None:
        for i, prompt_name in enumerate(chain):
            stage_label = f"[chain {i+1}/{len(chain)}] {prompt_name}"
            print(f"\n{'='*70}\n{stage_label}\n{'='*70}")
            generate_slogans(
                prompt_name=prompt_name,
                model_name=args.model_name,
                condition=condition,
                condition_params=condition_params,
                overwrite=args.overwrite,
                batch_size=args.batch_size,
                workers=args.workers,
                shard=args.shard,
                n_shards=args.n_shards,
                only_insufficient=(i > 0),
                test=False,
                mode=mode,
                provider=args.provider,
                region=args.region,
            )
        sys.exit(0)

    # ── Batch mode ───────────────────────────────────────────────────────
    if args.batch is not None:
        phase = args.batch

        if phase == "prepare":
            from .batch.prepare import prepare_batch, _default_input_dir
            output = args.batch_output or _default_input_dir(args.model_name, args.prompt_name)

            print_script_header(
                action="Preparing slogan batch",
                params={
                    "prompt":            args.prompt_name,
                    "model":             args.model_name,
                    "output":            output,
                    "condition?":        condition,
                    "params?":           condition_params or None,
                    "insufficient only": args.only_insufficient or None,
                    "overwrite":         args.overwrite,
                    "batch size":        args.batch_size,
                    "shard?":            f"{args.shard}/{args.n_shards}" if args.n_shards > 1 else None,
                    "sample?":           args.sample if args.sample > 0 else None,
                    "rows/file?":        args.rows_per_file if args.rows_per_file > 0 else None,
                },
            )

            prepare_batch(
                output=output,
                prompt_name=args.prompt_name,
                model_name=args.model_name,
                condition=condition,
                condition_params=condition_params,
                only_insufficient=args.only_insufficient,
                overwrite=args.overwrite,
                batch_size=args.batch_size,
                shard=args.shard,
                n_shards=args.n_shards,
                sample=args.sample,
                rows_per_file=args.rows_per_file,
            )

        elif phase == "run":
            from .batch.prepare import _default_input_dir, _default_output_dir, _state_path
            from pipeline.nebius_batch import make_client, run_batch, _DEFAULT_BASE_URL, _DEFAULT_KEY_ENV
            input_path = (args.batch_input[0] if args.batch_input
                          else _default_input_dir(args.model_name, args.prompt_name))
            output     = args.batch_output or _default_output_dir(args.model_name, args.prompt_name)
            out_dir    = output if output.endswith("/") else output.rsplit("/", 1)[0] + "/"

            print_script_header(
                action="Running slogan LLM batch",
                params={
                    "prompt": args.prompt_name,
                    "model":  args.model_name,
                    "input":  input_path,
                    "output": out_dir,
                },
            )
            run_batch(input_path, out_dir,
                      _state_path(args.model_name, args.prompt_name),
                      make_client(_DEFAULT_KEY_ENV, _DEFAULT_BASE_URL))

        elif phase == "poll":
            from .batch.prepare import _state_path
            from pipeline.nebius_batch import make_client, poll_batches, _DEFAULT_BASE_URL, _DEFAULT_KEY_ENV
            print_script_header(
                action="Polling slogan LLM batches",
                params={
                    "prompt":   args.prompt_name,
                    "model":    args.model_name,
                    "all":      args.all_batches,
                    "cancel":   args.cancel,
                    "download": args.download,
                },
            )
            poll_batches(
                _state_path(args.model_name, args.prompt_name),
                make_client(_DEFAULT_KEY_ENV, _DEFAULT_BASE_URL),
                download=args.download,
                all_batches=args.all_batches,
                cancel=args.cancel,
            )

        elif phase == "upsert":
            from .batch.upsert import upsert_batch_results
            from .batch.prepare import _default_output_dir
            from s3.utils.io import list_files

            default_output = _default_output_dir(args.model_name, args.prompt_name)

            if args.batch_input:
                input_paths = args.batch_input
            else:
                input_paths = list_files(default_output)
                if not input_paths:
                    _err(f"No result files found in {default_output}.")

            input_paths = sorted(input_paths)
            if args.n_shards > 1:
                input_paths = input_paths[args.shard::args.n_shards]

            print_script_header(
                action="Upserting slogan batch results",
                params={
                    "prompt":    args.prompt_name,
                    "model":     args.model_name,
                    "input":     args.batch_input or default_output,
                    "overwrite": args.overwrite,
                    **({"shard": f"{args.shard}/{args.n_shards}"} if args.n_shards > 1 else {}),
                },
            )
            conn  = get_rds_connection("v2")
            stats = upsert_batch_results(
                conn, input_paths, args.prompt_name, args.model_name,
                overwrite=args.overwrite,
            )
            verb = "upserted" if args.overwrite else "submitted (existing rows skipped)"
            print(
                f"\nDone. {stats['submitted']} slogan rows {verb}."
                f"\n  Input tokens:  {stats['total_in']:,}"
                f"\n  Output tokens: {stats['total_out']:,}"
            )

        sys.exit(0)

    # ── Online mode ──────────────────────────────────────────────────────
    generate_slogans(
        mode=mode,
        provider=args.provider,
        region=args.region,
        prompt_name=args.prompt_name,
        model_name=args.model_name,
        condition=condition,
        condition_params=condition_params,
        overwrite=args.overwrite,
        batch_size=args.batch_size,
        workers=args.workers,
        shard=args.shard,
        n_shards=args.n_shards,
        only_insufficient=args.only_insufficient,
        test=args.test,
    )
