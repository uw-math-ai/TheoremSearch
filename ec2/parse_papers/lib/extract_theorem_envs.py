from pathlib import Path
from typing import List, Dict, Tuple
import itertools
import re
from ..enums import Mode

"""
Extensions a file that includes theorem environment definitions can have
"""
THEOREM_ENV_DEF_EXTENSIONS = { "*.tex", "*.latex", "*.ltx", "*.sty", "*.cls" }

NEWTHEOREM_RE = re.compile(r"""
\\newtheorem
\*?\s*                # optional `*`
\{(?P<env>[^\}]+)\}   # env name (e.g. `cor`)
(?:\[[^\]]*\])?\s*    # optional shared counter (e.g. `[counter]`)
\{(?P<title>[^\}]+)\} # theorem title (e.g. `Corollary`) 
""", re.VERBOSE)

SAFE_ENV_RE = re.compile(r"^[A-Za-z]*$") # alpha only

def _contains_or_is_contained_by(a: str, b: str) -> bool:
    return (a in b) or (b in a)

def _extract_theorem_envs_from_file(file: Path, theorem_types: List[Tuple[str]]) -> Dict[str, str]:
    theorem_envs: Dict[str, str] = {}
    
    with file.open("r", errors="replace") as f:
        tex = f.read()

    for m in NEWTHEOREM_RE.finditer(tex):
        env = m.group("env").strip().replace("*", "")

        if not SAFE_ENV_RE.match(env):
            continue

        title = m.group("title").strip().lower()

        for tt in theorem_types:
            main_tt, *short_tts = tt

            if _contains_or_is_contained_by(main_tt, title) or \
                any(_contains_or_is_contained_by(short_tt, title) for short_tt in short_tts):
                theorem_envs[env] = main_tt
                break

    return theorem_envs

def extract_theorem_envs(
    paper_dir: Path, 
    theorem_types: List[Tuple[str]],
    mode: Mode
) -> Dict[str, str]:
    """
    Extracts the names of theorem environments and returns a Dict mapping environment names to
    their type of theorem.

    Parameters
    ----------
    paper_dir : Path
        Path to a paper's source files
    theorem_types : List[Tuple[str]]
        Possible theorem types with shorthands
    mode: Mode
        The mode to run `extract_theorem_envs` in

    Returns
    -------
    theorem_envs : Dict[str, str]
        Dict mapping theorem envs to theorem types
    """
    main_theorem_types = [t[0] for t in theorem_types]

    theorem_envs: Dict[str, str] = {
        type_: type_ for type_ in main_theorem_types
    }

    search_files = itertools.chain.from_iterable(
        paper_dir.rglob(ext) for ext in THEOREM_ENV_DEF_EXTENSIONS
    )
    
    for file in search_files:
        theorem_envs.update(_extract_theorem_envs_from_file(file, theorem_types))

    if mode == Mode.DEBUGGING:
        print(f"[DEBUG] Theorem envs: {theorem_envs}")

    return theorem_envs