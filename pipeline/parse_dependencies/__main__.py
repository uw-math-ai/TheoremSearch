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
        default=64,
        help="Papers processed per batch (default: 64)",
    )
    arg_parser.add_argument(
        "-s", "--similarity-threshold",
        type=float,
        default=0.8,
        help="pg_trgm title-match threshold for inter-paper resolution (default: 0.8)",
    )
    arg_parser.add_argument(
        "--skip-intra",
        action="store_true",
        help="Skip intra-paper dependency parsing",
    )
    arg_parser.add_argument(
        "--skip-inter",
        action="store_true",
        help="Skip inter-paper dependency parsing",
    )

    args = arg_parser.parse_args()

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
            "intra":                not args.skip_intra,
            "inter":                not args.skip_inter,
        }
    )

    conn = get_rds_connection("v2")

    if not args.skip_intra:
        connect_intrapaper_dependencies(
            conn=conn,
            condition=condition,
            condition_params=condition_params,
            batch_size=args.batch_size,
            overwrite=args.overwrite,
        )

    if not args.skip_inter:
        connect_interpaper_dependencies(
            conn=conn,
            condition=condition,
            condition_params=condition_params,
            overwrite=args.overwrite,
            batch_size=args.batch_size,
            similarity_threshold=args.similarity_threshold,
        )
