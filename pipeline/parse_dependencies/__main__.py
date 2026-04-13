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
        "--intra",
        action="store_true",
        help="Parse only intra-paper dependencies (omit to do both)",
    )
    arg_parser.add_argument(
        "--inter",
        action="store_true",
        help="Parse only inter-paper dependencies (omit to do both)",
    )
    arg_parser.add_argument(
        "--deterministic",
        action="store_true",
        help="Run only deterministic (\\ref/\\cite) dependency extraction (omit to do both)",
    )
    arg_parser.add_argument(
        "--llm",
        action="store_true",
        help="Run only LLM-inferred dependency extraction (omit to do both)",
    )
    arg_parser.add_argument(
        "--model",
        type=str,
        default="Qwen/Qwen3-235B-A22B-Instruct-2507",
        help="LLM model name for dependency inference via Nebius (default: Qwen/Qwen2.5-72B-Instruct)",
    )

    args = arg_parser.parse_args()

    do_intra = args.intra or not args.inter
    do_inter = args.inter or not args.intra
    do_deterministic = args.deterministic or not args.llm
    do_llm = args.llm or not args.deterministic

    if args.condition and len(args.condition) >= 2:
        condition, *condition_params = args.condition
    else:
        condition = args.condition[0] if args.condition else None
        condition_params = []

    print_script_header(
        action="Parsing theorem dependencies",
        params={
            "condition":            condition,
            "condition params":     condition_params,
            "overwrite":            args.overwrite,
            "batch size":           args.batch_size,
            "similarity threshold": args.similarity_threshold,
            "shard":                f"{args.shard}/{args.n_shards}" if args.n_shards > 1 else "off",
            "intra":                do_intra,
            "inter":                do_inter,
            "deterministic":        do_deterministic,
            "llm":                  do_llm,
            **({"model": args.model} if do_llm else {}),
        }
    )

    conn = get_rds_connection("v2")

    if do_intra:
        connect_intrapaper_dependencies(
            conn=conn,
            condition=condition,
            condition_params=condition_params,
            batch_size=args.batch_size,
            overwrite=args.overwrite,
            do_deterministic=do_deterministic,
            do_llm=do_llm,
            model=args.model,
            shard=args.shard,
            n_shards=args.n_shards,
        )

    if do_inter:
        connect_interpaper_dependencies(
            conn=conn,
            condition=condition,
            condition_params=condition_params,
            overwrite=args.overwrite,
            batch_size=args.batch_size,
            similarity_threshold=args.similarity_threshold,
            do_deterministic=do_deterministic,
            do_llm=do_llm,
            model=args.model,
            shard=args.shard,
            n_shards=args.n_shards,
        )
