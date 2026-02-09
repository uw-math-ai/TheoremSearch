from pathlib import Path
from typing import List, Dict, Tuple
import itertools
import re
from ...types import TheoremType

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

DEFAULT_THEOREM_TYPE_ALIASES = {
    TheoremType.Theorem: ["theo", "thm", "teo"],
    TheoremType.Lemma: ["lem"],
    TheoremType.Corollary: ["cor"],
    TheoremType.Proposition: ["prop"]
}

def _extract_theorem_envs_from_file(file: Path) -> Dict[str, str]:
    theorem_envs: Dict[str, TheoremType] = {}
    
    with file.open("r", errors="replace") as f:
        tex = f.read()

    for m in NEWTHEOREM_RE.finditer(tex):
        env = m.group("env").strip().replace("*", "")

        if not SAFE_ENV_RE.match(env):
            continue

        title = m.group("title").strip().lower()

        for theorem_type in TheoremType:
            aliases = DEFAULT_THEOREM_TYPE_ALIASES[theorem_type]

            if (title in theorem_type.value) or (theorem_type.value in title) or \
                any(title.startswith(alias) for alias in aliases):
                theorem_envs[env] = theorem_type
                break
                
    return theorem_envs

def extract_theorem_envs(
    paper_dir: Path
) -> Dict[str, TheoremType]:
    """
    Extracts the names of theorem environments and returns a Dict mapping environment names to
    their type of theorem.

    Parameters
    ----------
    paper_dir : Path
        Path to a paper's source files

    Returns
    -------
    theorem_envs : Dict[str, TheoremType]
        Dict mapping theorem envs to theorem types
    """
    theorem_envs: Dict[str, str] = {}

    for theorem_type in TheoremType:
        aliases = DEFAULT_THEOREM_TYPE_ALIASES[theorem_type]

        for alias in aliases:
            theorem_envs[alias] = theorem_type

    search_files = itertools.chain.from_iterable(
        paper_dir.rglob(ext) for ext in THEOREM_ENV_DEF_EXTENSIONS
    )
    
    for file in search_files:
        theorem_envs.update(_extract_theorem_envs_from_file(file))

    # if mode == Mode.DEBUGGING:
    #     print(f"[DEBUG] Theorem envs: {theorem_envs}")

    return theorem_envs