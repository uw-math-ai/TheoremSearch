from pathlib import Path
from typing import List
from ...enums import Mode
from ...types import Theorem
from ...lib.guess_main_file import guess_main_file
from ...lib.extract_theorem_envs import extract_theorem_envs
from .flatten_paper import flatten_paper
from ...lib.remove_comments import remove_comments
from .theorems.find import find_theorems
from ...lib.macros.expand import expand_macros

def parse_by_regex(
    paper_dir: Path,
    theorem_types: List[str],
    mode: Mode = Mode.PRODUCTION
) -> List[Theorem]:
    """
    Parses a paper's source files into a list of theorems using regex.

    Parameters
    ----------
    paper_dir : Path
        The path to all of a paper's source files
    theorems_types : List[str]
        Possible theorem types
    mode : Mode
        The mode to run `parse_by_regex` in

    Returns
    -------
    theorems: List[Theorem]
        A list of regex-parsed theorems
    """
    main_file = guess_main_file(paper_dir, mode=mode)
    theorem_envs = extract_theorem_envs(paper_dir, theorem_types, mode=mode)

    tex = flatten_paper(main_file, paper_dir, mode=mode)
    tex = remove_comments(tex)

    tex = expand_macros(tex, paper_dir, mode=mode)

    return find_theorems(tex, theorem_envs)



