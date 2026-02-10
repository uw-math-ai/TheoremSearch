"""
Main library parsing file. Provides an importable method and a script.
"""

import shutil
from pathlib import Path
from typing import List, Optional
from tempfile import TemporaryDirectory
from argparse import ArgumentParser
from .types import Theorem
from .lib.utils.download_arxiv_paper import download_arxiv_paper
from .lib.types import TheoremValidationLevel
from .lib.methods.plasTeX.parse import parse_by_plastex
from .lib.utils.validate_theorems import validate_theorems, validate_theorem
from .lib.utils.run_with_timeout import run_with_timeout

def parse_paper(
    arxiv_id: Optional[str] = None,
    paper_path: Optional[Path | str] = None,
    validation_level: TheoremValidationLevel = TheoremValidationLevel.Paper,
) -> List[Theorem]:
    """
    Parses a LaTeX paper (from arXiv or a local file) for theorems. Validates the parsed theorems
    at a specified level.

    Parameters
    ----------
    arxiv_id : Optional[str], optional
        arXiv id of a paper. Either this or paper_path must be used.
    paper_path : Optional[Path | str], optional
        Path to a paper's LaTeX file or a folder of LaTeX files. Either this or arxiv_id must be
        used.
    validation_level : TheoremValidationLevel, optional
        Level at which to validate theorems. By default, paper-level.

    Returns
    -------
    theorems : List[Theorem]
        Parsed theorems, all checked for validity.
    """

    if arxiv_id is not None:
        with TemporaryDirectory() as temp_dir:
            paper_dir = download_arxiv_paper(Path(temp_dir), arxiv_id)

            return _parse_paper(paper_dir, validation_level=validation_level)
    elif paper_path is not None:
        if isinstance(paper_path, str):
            paper_path = Path(paper_path)
        
        if paper_path.is_dir():
            return _parse_paper(paper_path, validation_level=validation_level)
        elif paper_path.is_file():
            with TemporaryDirectory() as temp_dir:
                paper_dir = Path(temp_dir)
                shutil.copy2(paper_path, paper_dir / paper_path.name)

                return _parse_paper(paper_dir, validation_level=validation_level)
        else:
            raise FileNotFoundError(f"{paper_path} does not exist")
    else:
        raise ValueError("arxiv_id and paper_path are both None")

@run_with_timeout(seconds=10)
def _parse_paper(
    paper_dir: Path,
    validation_level: TheoremValidationLevel = TheoremValidationLevel.Paper
) -> List[Theorem]:
    theorems: List[Theorem] = parse_by_plastex(paper_dir)

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
        "--arxiv-id",
        type=str,
        required=False,
        default="",
        help="arXiv id of a paper"
    )

    arg_parser.add_argument(
        "--paper-path",
        type=str,
        required=False,
        default="",
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
        "-v",
        "--validation-level",
        type=TheoremValidationLevel,
        required=False,
        default="paper",
        help="Level to validate theorems. Supported: paper (default), theorem"
    )

    args = arg_parser.parse_args()

    theorems: List[Theorem] = parse_paper(
        arxiv_id=args.arxiv_id or None,
        paper_path=args.paper_path or None,
        validation_level=args.validation_level
    )

    json_out = "\n".join(theorem.model_dump_json() for theorem in theorems)
    out_path = Path(args.output_file)
    
    out_path.write_text(json_out)