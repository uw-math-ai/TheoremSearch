from argparse import ArgumentParser, ArgumentError
import sys

from rds.utils.connect import get_rds_connection
from ..printing import print_script_header
from .intrapaper import connect_intrapaper_dependencies
from .interpaper import connect_interpaper_dependencies
from .judge import connect_judge_dependencies

_ONLINE_METHODS  = {"deterministic", "heuristic", "llm", "judge"}
_BATCH_METHODS   = {"llm", "judge"}
_BATCH_PHASES    = ("prepare", "run", "poll", "connect")


def _err(msg: str):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    arg_parser = ArgumentParser(
        description="Parse theorem dependencies (deterministic, heuristic, LLM notations, judge)."
    )

    arg_parser.add_argument(
        "-c", "--condition",
        type=str,
        nargs="+",
        help="SQL WHERE condition to filter papers (first token is the expression, rest are params)",
    )
    arg_parser.add_argument(
        "-o", "--overwrite",
        action="store_true",
        help="Re-process papers that already have dependency rows",
    )
    arg_parser.add_argument(
        "-b", "--batch-size",
        type=int,
        default=32,
        help="Papers processed per batch (default: 32)",
    )
    arg_parser.add_argument(
        "-s", "--similarity-threshold",
        type=float,
        default=0.8,
        help="pg_trgm title-match threshold for inter-paper resolution (default: 0.8)",
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
        "-M", "--method",
        nargs="+",
        choices=list(_ONLINE_METHODS),
        default=["deterministic", "heuristic"],
        dest="methods",
        metavar="METHOD",
        help=(
            "Methods to run: deterministic, heuristic, llm, judge. "
            "Accepts multiple values. Default: deterministic heuristic."
        ),
    )
    arg_parser.add_argument(
        "-m", "--model",
        type=str,
        default=None,
        help="Model alias from models.json (required for --method llm/judge).",
    )
    arg_parser.add_argument(
        "--proximity-threshold",
        type=float,
        default=0.3,
        dest="proximity_threshold",
    )
    arg_parser.add_argument(
        "-w", "--workers",
        type=int,
        default=8,
        help="Concurrent LLM requests for online --method llm (default: 8)",
    )
    arg_parser.add_argument(
        "--llm-batch-size",
        type=int,
        default=10,
        dest="llm_batch_size",
        help="Statements per LLM call for online --method llm (default: 10). "
             "Each call asks the model for a JSON array of that many extractions.",
    )
    arg_parser.add_argument(
        "--batch",
        choices=_BATCH_PHASES,
        default=None,
        metavar="PHASE",
        help=(
            f"Run a batch pipeline phase ({', '.join(_BATCH_PHASES)}) instead of online processing. "
            "Only valid with --method llm or judge."
        ),
    )
    # Batch-prepare / batch-connect passthrough args
    arg_parser.add_argument("-i", "--input",  type=str, default=None, dest="batch_input",
                            help="Batch input path (for --batch connect).")
    arg_parser.add_argument("--output",       type=str, default=None, dest="batch_output",
                            help="Batch output path (for --batch prepare/run).")
    arg_parser.add_argument("--sample",       type=int, default=-1,
                            help="Randomly sample N papers (for --batch prepare, testing).")
    arg_parser.add_argument("--rows-per-file", type=int, default=-1, dest="rows_per_file",
                            help="Split batch output into files of at most N rows.")
    arg_parser.add_argument("--debug", action="store_true",
                            help="Verbose per-call logging. With --method judge: print per-rejection reasons. "
                                 "With --method llm: print one line per LLM submit/return.")
    args = arg_parser.parse_args()

    methods          = set(args.methods)
    do_deterministic = "deterministic" in methods
    do_heuristic     = "heuristic"     in methods
    do_llm           = "llm"           in methods
    do_judge         = "judge"         in methods

    # ── Validate combinations ────────────────────────────────────────────
    if do_judge and len(methods) > 1:
        _err("--method judge cannot be combined with other methods")
    if args.debug and not (do_judge or do_llm):
        _err("--debug is only valid with --method judge or --method llm")

    if args.batch is not None:
        invalid = methods - _BATCH_METHODS
        if invalid:
            _err(f"--batch is only valid with --method llm/judge, got: {sorted(invalid)}")
        if len(methods) > 1:
            _err("--batch requires exactly one --method (llm or judge)")
        batch_method = next(iter(methods))

    if args.batch == "prepare":
        needs_model = True  # model id goes into each JSONL request
    elif args.batch in ("run", "poll", "connect"):
        needs_model = False  # results already exist; no model call needed
    else:
        needs_model = do_llm or do_judge

    if needs_model and args.model is None:
        _err(f"--model is required for --method {sorted(methods & _BATCH_METHODS)}")

    # ── Parse condition ──────────────────────────────────────────────────
    if args.condition and len(args.condition) >= 2:
        condition, *condition_params = args.condition
    else:
        condition = args.condition[0] if args.condition else None
        condition_params = []

    # ── Batch mode ───────────────────────────────────────────────────────
    if args.batch is not None:
        from .models import load_model_config
        phase = args.batch

        if phase == "prepare":
            from .batch.prepare import prepare_batch, _s3_input_dir
            model_config = load_model_config(args.model)
            output = args.batch_output or _s3_input_dir(batch_method)

            print_script_header(
                action=f"Preparing {batch_method} batch",
                params={
                    "method":     batch_method,
                    "model":      args.model,
                    "output":     output,
                    "condition?": condition,
                    "params?":    condition_params or None,
                    "overwrite":  args.overwrite,
                    "batch size": args.batch_size,
                    "shard?":     f"{args.shard}/{args.n_shards}" if args.n_shards > 1 else None,
                    "sample?":    args.sample if args.sample > 0 else None,
                    "rows/file?": args.rows_per_file if args.rows_per_file > 0 else None,
                },
            )

            prepare_batch(
                method=batch_method,
                output=output,
                model_config=model_config,
                condition=condition,
                condition_params=condition_params,
                overwrite=args.overwrite,
                batch_size=args.batch_size,
                shard=args.shard,
                n_shards=args.n_shards,
                sample=args.sample,
                rows_per_file=args.rows_per_file,
            )

        elif phase == "run":
            from .batch.prepare import _s3_input_dir, _s3_output_dir, _state_path
            from pipeline.nebius_batch import make_client, run_batch, _DEFAULT_BASE_URL, _DEFAULT_KEY_ENV
            input_path = args.batch_input  or _s3_input_dir(batch_method)
            output     = args.batch_output or _s3_output_dir(batch_method)
            out_dir    = output if output.endswith("/") else output.rsplit("/", 1)[0] + "/"

            print_script_header(
                action=f"Running {batch_method} batch",
                params={"input": input_path, "output": out_dir},
            )
            run_batch(input_path, out_dir, _state_path(batch_method), make_client(_DEFAULT_KEY_ENV, _DEFAULT_BASE_URL))

        elif phase == "poll":
            from .batch.prepare import _state_path
            from pipeline.nebius_batch import make_client, poll_batches, _DEFAULT_BASE_URL, _DEFAULT_KEY_ENV
            print_script_header(action=f"Polling {batch_method} batches", params={})
            poll_batches(_state_path(batch_method), make_client(_DEFAULT_KEY_ENV, _DEFAULT_BASE_URL))

        elif phase == "connect":
            from .batch.connect import connect_batch_results
            from .batch.prepare import _s3_output_dir
            from s3.utils.io import list_files

            if args.batch_input:
                input_paths = [args.batch_input] if isinstance(args.batch_input, str) else args.batch_input
            else:
                output_dir  = _s3_output_dir(batch_method)
                input_paths = list_files(output_dir)
                if not input_paths:
                    _err(f"No result files found in {output_dir}.")

            input_paths = sorted(input_paths)
            if args.n_shards > 1:
                input_paths = input_paths[args.shard::args.n_shards]

            print_script_header(
                action=f"Connecting {batch_method} batch results",
                params={
                    "input":      args.batch_input or _s3_output_dir(batch_method),
                    "batch size": args.batch_size,
                    **({"shard": f"{args.shard}/{args.n_shards}"} if args.n_shards > 1 else {}),
                },
            )
            conn  = get_rds_connection("v2")
            stats = connect_batch_results(conn, batch_method, input_paths, args.batch_size)
            extra = f", {stats['notations']} notations" if batch_method == "llm" else ""
            print(
                f"\nDone. {stats['deps']} deps{extra} written ({stats['failed']} papers failed)."
                f"\n  Input tokens:  {stats['total_in']:,}"
                f"\n  Output tokens: {stats['total_out']:,}"
            )

        sys.exit(0)

    # ── Online mode ──────────────────────────────────────────────────────
    print_script_header(
        action="Parsing theorem dependencies",
        params={
            "condition?":            condition,
            "condition params?":     condition_params,
            "overwrite":            args.overwrite,
            "batch size":           args.batch_size,
            "similarity threshold?": args.similarity_threshold if (do_deterministic or do_heuristic) else None,
            "proximity threshold?":  args.proximity_threshold if do_heuristic else None,
            "shard?":                f"{args.shard}/{args.n_shards}" if args.n_shards > 1 else None,
            "methods":              sorted(methods),
            **({"model": args.model} if (do_llm or do_judge) else {}),
            **({"workers": args.workers, "llm batch size": args.llm_batch_size} if do_llm else {}),
        }
    )

    conn = get_rds_connection("v2")

    if do_deterministic or do_heuristic:
        connect_intrapaper_dependencies(
            conn=conn,
            condition=condition,
            condition_params=condition_params,
            batch_size=args.batch_size,
            overwrite=args.overwrite,
            do_deterministic=do_deterministic,
            do_heuristic=do_heuristic,
            proximity_threshold=args.proximity_threshold,
            shard=args.shard,
            n_shards=args.n_shards,
            sample=args.sample,
        )
        connect_interpaper_dependencies(
            conn=conn,
            condition=condition,
            condition_params=condition_params,
            overwrite=args.overwrite,
            batch_size=args.batch_size,
            similarity_threshold=args.similarity_threshold,
            do_deterministic=do_deterministic,
            do_heuristic=do_heuristic,
            proximity_threshold=args.proximity_threshold,
            shard=args.shard,
            n_shards=args.n_shards,
            sample=args.sample,
        )

    if do_llm:
        from .llm import run_llm
        from .models import load_model_config
        from .models import build_openai_client
        model_config = load_model_config(args.model)
        client = build_openai_client()
        run_llm(
            conn=conn,
            client=client,
            model_config=model_config,
            condition=condition,
            condition_params=condition_params,
            overwrite=args.overwrite,
            batch_size=args.batch_size,
            workers=args.workers,
            llm_batch_size=args.llm_batch_size,
            shard=args.shard,
            n_shards=args.n_shards,
            sample=args.sample,
            debug=args.debug,
        )

    if do_judge:
        connect_judge_dependencies(
            conn=conn,
            condition=condition,
            condition_params=condition_params,
            batch_size=args.batch_size,
            overwrite=args.overwrite,
            model_name=args.model,
            shard=args.shard,
            n_shards=args.n_shards,
            sample=args.sample,
            debug=args.debug,
        )
