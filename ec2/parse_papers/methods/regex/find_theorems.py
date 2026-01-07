from typing import Dict, List
import re
from ...types import Theorem
from ...lib.separate_body_and_label import separate_body_and_label

BEGIN_RE = re.compile(r"\\begin\{(?P<env>[^}]+)\}")
NOTE_RE = re.compile(r"^\[(?P<note>[^\]]*)\]")

def _parse_env_content(env_content: str, type: str) -> Theorem:
    env_content = env_content.strip()

    note = None
    note_match = NOTE_RE.match(env_content)
    if note_match:
        note = note_match.group("note")
        env_content = NOTE_RE.sub("", env_content, count=1).lstrip()

    body, label = separate_body_and_label(env_content)

    return {
        "type": type,
        "ref": None,
        "note": note,
        "label": label,
        "body": body,
    }

def find_theorems(tex: str, theorem_envs: Dict[str, str]) -> List[Theorem]:
    """
    Finds Theorems in TeX.

    Parameters
    ----------
    tex : str
        TeX source
    theorem_envs : Dict[str, str]
        Dict mapping theorem envs to types

    Returns
    -------
    theorems : List[Theorem]
        List of theorems
    """

    theorems: List[Theorem] = []
    pos = 0

    while True:
        begin_match = BEGIN_RE.search(tex, pos)
        if not begin_match:
            break

        env = begin_match.group("env")
        start_body = begin_match.end()

        if env not in theorem_envs:
            pos = start_body
            continue

        end_re = re.compile(r"\\end\{" + re.escape(env) + r"\}")
        end_match = end_re.search(tex, start_body)
        if not end_match:
            pos = start_body
            continue

        env_content = tex[start_body:end_match.start()]
        theorems.append(_parse_env_content(env_content, theorem_envs[env]))

        pos = end_match.end()

    return theorems