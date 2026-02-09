"""
Helpers for guessing which file in a LaTeX source folder is the main file.
"""

from pathlib import Path
import itertools
from .remove_comments import remove_line_comments

"""
Extensions a main file can have
"""
MAIN_FILE_EXTENSIONS = { "*.tex", "*.latex", "*.ltx", "*.txt", "*.TEX", "*.TeX" }

"""
Config object for main file points heuristic
"""
POINTS_CONFIG = [
    # Document
    {
        "points": 4.0,
        "patterns": { "\\begin{document}", "\\end{document}" }
    },
    # Pre-Content
    {
        "points": 2.0,
        "patterns": { "\\title", "\\author", "\\maketitle", "\\begin{abstract}" }
    },
    # Imports
    {
        "points": 1.0,
        "patterns": { "\\input" }
    },
    # Draft Hints
    {
        "points": -8.0,
        "patterns": {
            "fixme", "FIXME", 
            "todo", "TODO", 
            "\\missingfigure", 
            "\\XXX", "\\xx", "\\xxx"
        }
    }
]


def _score_file(file: Path) -> float:
    score = 0.0
    
    for line in file.open(errors="ignore"):
        line = remove_line_comments(line)
        match_found = False

        for pattern_group in POINTS_CONFIG:
            if match_found:
                break

            for pattern in pattern_group["patterns"]:
                if match_found:
                    break

                if pattern in line:
                    score += pattern_group["points"]
                    match_found = True

    return score


def guess_main_file(paper_dir: Path) -> Path:
    """
    Guesses the Path of the main file in a paper's source directory.

    Parameters
    ----------
    paper_dir : Path
        Path to a paper's source files

    Returns
    -------
    main_file : Path
        Best guess at the main file in `paper_dir`
    """

    candidate_files = itertools.chain.from_iterable(
        paper_dir.rglob(ext) for ext in MAIN_FILE_EXTENSIONS
    )
    candidate_files = list(candidate_files)

    if len(candidate_files) == 0:
        raise ValueError("Paper directory has no potential main files")
    elif len(candidate_files) == 1:
        main_file = candidate_files[0]

        # if mode == Mode.DEBUGGING:
        #     print(f"[DEBUG] Main file: {main_file.name} (only candidate)")

        return main_file

    main_file: Path = candidate_files[0]
    best_score = float("-inf")

    for file in candidate_files:
        score = _score_file(file)

        if score > best_score:
            main_file = file
            best_score = score

    # if mode == Mode.DEBUGGING:
    #     print(f"[DEBUG] main file: {main_file.name}")

    return main_file