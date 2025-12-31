from pathlib import Path
from typing import List, List
from .enums import Mode, Method
from .types import Theorem
from .methods.plastex.parse import parse_by_plastex
from .lib.validate_theorem import validate_theorem

def parse_paper(
    paper_dir: str | Path,
    theorem_types: List[str],
    mode: Mode = Mode.PRODUCTION,
    method: Method = Method.PLASTEX
) -> List[Theorem]:
    """
    Parses a paper's source files into a list of theorems.

    Parameters
    ----------
    paper_dir : str | Path
        Path to all of a paper's source files
    theorem_types : List[str]
        Possible theorem types
    mode : Mode
        Mode to run `parse_paper` in
    method : Method
        Method to parse papers with

    Returns
    -------
    theorems: List[Theorem]
        A list of parsed theorems
    """

    # Enforces Path use for convenience
    if isinstance(paper_dir, str):
        paper_dir = Path(paper_dir)

    theorems: List[Theorem] = []

    match method:
        case Method.PLASTEX:
            parse = parse_by_plastex
        case Method.TEX:
            # TODO: Implement parse_by_tex
            pass
        case Method.REGEX:
            # TODO: Implement parse_by_regex
            pass

    for theorem in parse(paper_dir, theorem_types, mode=mode):
        validate_theorem(theorem, theorem_types)
        theorems.append(theorem)

    return theorems