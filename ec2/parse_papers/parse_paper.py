from pathlib import Path
from typing import List
from .enums import Mode, Method, TheoremValidationLevel
from .types import Theorem
from .methods.plastex.parse import parse_by_plastex
from .methods.tex.parse import parse_by_tex
from .methods.regex.parse import parse_by_regex
from .lib.validate_theorems import validate_theorems, validate_theorem
from .lib.run_with_timeout import run_with_timeout

def parse_paper(
    paper_dir: str | Path,
    theorem_types: List[str],
    timeout: int,
    theorem_validation_level: TheoremValidationLevel,
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
    theorem_validation_level : TheoremValidationLevel
        Level at which to check if parsed theorems are valid
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
            return parse_paper(paper_dir, theorem_types, 0, theorem_validation_level, mode, method)

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
            parse = parse_by_regex

    theorems = parse(paper_dir, theorem_types, mode=mode)

    if mode == Mode.DEBUGGING:
        import json

        with open(paper_dir / "DEBUG_theorems.json", "w") as dtj:
            json.dump(theorems, dtj, indent=4)

    if theorem_validation_level == TheoremValidationLevel.PAPER:
        validate_theorems(theorems, theorem_types)

        return theorems
    else: # theorem_validation_level == TheoremValidationLevel.THEOREM:
        valid_theorems = []

        for theorem in theorems:
            try:
                validate_theorem(theorem, theorem_types)

                valid_theorems.append(theorem)
            except Exception:
                pass

        return valid_theorems