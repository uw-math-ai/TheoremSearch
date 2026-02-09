"""
Main library parsing file. Provides an importable method and a script.
"""

from pathlib import Path
from typing import List
from shutil import copy2
from tempfile import TemporaryDirectory
from argparse import ArgumentParser
from .types import Theorem
from .lib.types import ParsingMethod, TheoremValidationLevel
from .lib.methods.plasTeX.parse import parse_by_plastex
from .lib.utils.validate_theorems import validate_theorems, validate_theorem

def parse_paper(
    paper_path: Path | str,
    method: ParsingMethod = ParsingMethod.PlasTeX,
    validation_level: TheoremValidationLevel = TheoremValidationLevel.Paper
) -> List[Theorem]:
    """
    Parses a paper for theorems using a specified method. Validates the parsed theorems at a
    specified level.

    Parameters
    ----------
    paper_path : Path | str
        Path to a paper's TeX file or a folder of TeX files.
    method : ParsingMethod, optional
        The method to parse the paper. By default, plasTeX.
    validation_level : TheoremValidationLevel, optional
        Level at which to validate theorems. By default, paper-level.

    Returns
    -------
    theorems : List[Theorem]
        Parsed theorems, all checked for validity.
    """

    if isinstance(paper_path, str):
        paper_path = Path(paper_path)
    
    if paper_path.is_dir():
        paper_dir = paper_path
    elif paper_path.is_file():
        with TemporaryDirectory() as temp_dir:
            paper_dir = Path(temp_dir)
            copy2(paper_path, paper_dir / paper_path.name)

            return parse_paper(paper_dir, method, validation_level)
    else:
        raise FileNotFoundError(f"{paper_path} does not exist")

    match method:
        case ParsingMethod.PlasTeX:
            parse = parse_by_plastex
        case ParsingMethod.TeX:
            pass
            # parse = parse_by_tex
        case ParsingMethod.Regex:
            pass
            # parse = parse_by_regex

    theorems: List[Theorem] = parse(paper_dir)

    match validation_level:
        case TheoremValidationLevel.Theorem:
            valid_theorems: List[Theorem] = []

            for theorem in theorems:
                try:
                    validate_theorem(theorem)
                    valid_theorems.append(theorem)
                except Exception:
                    pass

            return valid_theorems
        
        case TheoremValidationLevel.Paper:
            try:
                validate_theorems(theorems)
                return theorems
            except Exception:
                return []
            
if __name__ == "__main__":
    arg_parser = ArgumentParser()

    arg_parser.add_argument(
        "--paper-path",
        type=str,
        required=True,
        help="Path to a LaTeX file or directory of LaTeX files"
    )

    arg_parser.add_argument(
        "-o",
        "--output-file",
        type=str,
        required=True,
        help="Path to output JSONL file"
    )

    arg_parser.add_argument(
        "-m",
        "--parsing-method",
        type=ParsingMethod,
        required=False,
        default="plasTeX",
        help="Method to parse papers with. Supported: plasTeX (default), TeX, and regex"
    )

    arg_parser.add_argument(
        "-v",
        "--validation-level",
        type=TheoremValidationLevel,
        required=False,
        default="paper",
        help="Level to validate theorems. Supported: paper (default), theorem"
    )

    args = arg_parser.parse_args()

    theorems: List[Theorem] = parse_paper(
        paper_path=args.paper_path,
        method=args.parsing_method,
        validation_level=args.validation_level
    )

    json_out = "\n".join(theorem.model_dump_json() for theorem in theorems)
    out_path = Path(args.output_file)
    
    out_path.write_text(json_out)