from pathlib import Path
from typing import List
from .thmenvcapture import inject_thmenvcapture
from .run_pdflatex import run_pdflatex
from .parse_log import parse_log
from ...lib.guess_main_file import guess_main_file
from ...lib.extract_theorem_envs import extract_theorem_envs
from ...lib.macros.expand import expand_macros
from ...types import Theorem
from ....parse_papers.enums import Mode

def parse_by_tex(
    paper_dir: Path,
    theorem_types: List[str],
    mode: Mode = Mode.PRODUCTION
) -> List[Theorem]:
    """
    Parses a paper's source files into a list of theorems using a TeX logger.

    Parameters
    ----------
    paper_dir : Path
        Path to a paper's source files
    theorems_types : List[str]
        Possible theorem types
    mode : Mode
        The mode to run `parse_by_tex` in

    Returns
    -------
    theorems: List[Theorem]
        A list of TeX-parsed theorems
    """

    main_file = guess_main_file(paper_dir, mode=mode)
    theorem_envs = extract_theorem_envs(paper_dir, theorem_types, mode=mode)

    inject_thmenvcapture(main_file, paper_dir, theorem_envs, mode=mode)
    theorem_log_file = run_pdflatex(main_file, paper_dir, mode=mode)

    with open(theorem_log_file, "r", encoding="utf-8", errors="ignore") as tlf:
        orig_theorem_log = tlf.read()
        
    theorem_log = expand_macros(orig_theorem_log, paper_dir, mode=mode)

    return parse_log(theorem_log, theorem_envs)


