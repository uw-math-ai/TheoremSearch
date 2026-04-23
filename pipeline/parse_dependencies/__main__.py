from argparse import ArgumentParser

from rds.utils.connect import get_rds_connection
from ..printing import print_script_header
from .intrapaper import connect_intrapaper_dependencies
from .interpaper import connect_interpaper_dependencies


if __name__ == "__main__":
    arg_parser = ArgumentParser(
        description="Parse intra- and inter-paper theorem dependencies."
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
        help="Shard index (0-based). Run alongside --n-shards to parallelize across workers",
    )
    arg_parser.add_argument(
        "--n-shards",
        type=int,
        default=1,
        help="Total number of shards. Papers are split by hashtext(paper_id) %% n_shards",
    )
    arg_parser.add_argument(
        "-m", "--method",
        nargs="+",
        choices=["deterministic", "heuristic", "llm"],
        default=["deterministic", "heuristic", "llm"],
        dest="methods",
        metavar="METHOD",
        help=(
            "Methods to run: deterministic (\\ref/\\cite scanner), "
            "heuristic (proximity-based pre/post-context), "
            "llm (concept extraction + matching). "
            "Accepts multiple values. Default: all three."
        ),
    )
    arg_parser.add_argument(
        "--model",
        type=str,
        default="Qwen/Qwen3-235B-A22B-Instruct-2507",
        help="LLM model name for concept extraction via Nebius (default: Qwen/Qwen3-235B-A22B-Instruct-2507)",
    )
    arg_parser.add_argument(
        "--max-statements",
        type=int,
        default=100,
        dest="max_statements",
        help=(
            "When a paper exceeds this many statements, only the most important kinds "
            "(definition, theorem, proposition, corollary, lemma, notation) are sent to the LLM "
            "(default: 100)"
        ),
    )
    arg_parser.add_argument(
        "--proximity-threshold",
        type=float,
        default=0.3,
        dest="proximity_threshold",
        help=(
            "Threshold for the heuristic pre/post-context scanner: "
            "accept a \\ref/\\cite (or adjacent-statement dep) when "
            "max(anchor_strength / word_distance) >= threshold (default: 0.3)"
        ),
    )

    args = arg_parser.parse_args()

    methods          = set(args.methods)
    do_deterministic = "deterministic" in methods
    do_heuristic     = "heuristic"     in methods
    do_llm           = "llm"           in methods

    if args.condition and len(args.condition) >= 2:
        condition, *condition_params = args.condition
    else:
        condition = args.condition[0] if args.condition else None
        condition_params = []

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
            **({"model": args.model, "max statements": args.max_statements} if do_llm else {}),
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
            do_llm=False,
            proximity_threshold=args.proximity_threshold,
            shard=args.shard,
            n_shards=args.n_shards,
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
        )

    if do_llm:
        connect_intrapaper_dependencies(
            conn=conn,
            condition=condition,
            condition_params=condition_params,
            batch_size=args.batch_size,
            overwrite=args.overwrite,
            do_deterministic=False,
            do_heuristic=False,
            do_llm=True,
            model=args.model,
            max_statements=args.max_statements,
            shard=args.shard,
            n_shards=args.n_shards,
        )
