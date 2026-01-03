from typing import List, Dict
from ...types import Theorem
from ...lib.separate_body_and_label import separate_body_and_label

def parse_log(
    theorem_log: str,
    theorem_envs: Dict[str, str]
) -> List[Theorem]:
    """
    Parses a theorem log into Theorems.

    Parameters
    ----------
    theorem_log : str
        The content of the theorem log
    theorem_envs : Dict[str, str]
        Dict mapping theorem envs to theorem types
    
    Returns
    -------
    theorems : List[Theorem]
        The parsed list of Theorems
    """

    theorems: List[Theorem] = []

    curr_theorem: Theorem = {}

    for raw_line in theorem_log.splitlines():
        line = raw_line.strip()

        if line == "BEGIN_ENV":
            curr_theorem = {
                "type": None,
                "ref": None,
                "note": None,
                "label": None,
                "body": None
            }
        elif line == "END_ENV":
            theorems.append(curr_theorem)
        elif line.startswith("env:"):
            env = line.removeprefix("env:").strip()
            curr_theorem["type"] = theorem_envs[env] if env in theorem_envs else None
        elif line.startswith("ref:"):
            ref = line.removeprefix("ref:").strip()
            curr_theorem["ref"] = ref
        elif line.startswith("note:"):
            note = line.removeprefix("note:").strip()
            curr_theorem["note"] = note
        elif line.startswith("body:"):
            body_and_label = line.removeprefix("body:").strip()
            body, label = separate_body_and_label(body_and_label)

            curr_theorem["body"] = body
            curr_theorem["label"] = label

    return theorems