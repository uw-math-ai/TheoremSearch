from pathlib import Path
from typing import List, Dict
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

def _extract_theorem_envs_from_file(file: Path, theorem_types: List[str]) -> Dict[str, str]:
    theorem_envs: Dict[str, str] = {}
    
    with file.open("r", errors="replace") as f:
        tex = f.read()

    for m in NEWTHEOREM_RE.finditer(tex):
        env = m.group("env").strip().replace("*", "")

        if not SAFE_ENV_RE.match(env):
            continue

        title = m.group("title").strip().lower()

        for tt in theorem_types:
            if tt in title or title in tt:
                theorem_envs[env] = tt
                break

    return theorem_envs

def extract_theorem_envs(
    paper_dir: Path, 
    theorem_types: List[str],
    mode: Mode
) -> Dict[str, str]:
    """
    Extracts the names of theorem environments and returns a Dict mapping environment names to
    their type of theorem.

    Parameters
    ----------
    paper_dir : Path
        Path to a paper's source files
    theorem_types : List[str]
        Possible theorem types
    mode: Mode
        The mode to run `extract_theorem_envs` in

    Returns
    -------
    theorem_envs : Dict[str, str]
        Dict mapping theorem envs to theorem types
    """

    theorem_envs: Dict[str, str] = {
        type_: type_ for type_ in theorem_types
    }

    search_files = itertools.chain.from_iterable(
        paper_dir.rglob(ext) for ext in THEOREM_ENV_DEF_EXTENSIONS
    )
    
    for file in search_files:
        theorem_envs.update(_extract_theorem_envs_from_file(file, theorem_types))

    if mode == Mode.DEBUGGING:
        print(f"[DEBUG] Theorem envs: {theorem_envs}")

    return theorem_envs