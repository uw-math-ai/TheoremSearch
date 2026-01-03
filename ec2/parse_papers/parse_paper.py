from pathlib import Path
from typing import List, List
from .enums import Mode, Method
from .types import Theorem
from .methods.plastex.parse import parse_by_plastex
from .methods.tex.parse import parse_by_tex
from .lib.validate_theorems import validate_theorems
from .lib.run_with_timeout import run_with_timeout

def parse_paper(
    paper_dir: str | Path,
    theorem_types: List[str],
    timeout: int,
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
    timeout : int
        Time allowed to parse a paper. If <= 0, is infinity
    mode : Mode
        Mode to run `parse_paper` in
    method : Method
        Method to parse papers with

    Returns
    -------
    theorems: List[Theorem]
        A list of parsed theorems
    """

    if timeout > 0:
        @run_with_timeout(seconds=timeout)
        def parse_paper_with_timeout():
            return parse_paper(paper_dir, theorem_types, 0, mode, method)

        return parse_paper_with_timeout()

    # Enforces Path use for convenience
    if isinstance(paper_dir, str):
        paper_dir = Path(paper_dir)

    match method:
        case Method.PLASTEX:
            parse = parse_by_plastex
        case Method.TEX:
            parse = parse_by_tex
        case Method.REGEX:
            # TODO: Implement parse_by_regex
            pass

    theorems = parse(paper_dir, theorem_types, mode=mode)

    if mode == Mode.DEBUGGING:
        import json

        with open(paper_dir / "DEBUG_theorems.json", "w") as dtj:
            json.dump(theorems, dtj, indent=4)

    validate_theorems(theorems, theorem_types)

    return theorems