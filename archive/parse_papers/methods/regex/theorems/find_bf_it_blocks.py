import re
from typing import List
from ....types import Theorem
from .separate_name_segments import separate_name_segments

BF_IT_START_RE = pattern = re.compile(r"\{\s*\\bf\s+(?P<name>[^}]+)\s*\}\s*\{\s*\\it")
POTENTIAL_REF_RE = re.compile(r'^[A-Z0-9.]+$')

def find_bf_it_blocks(tex: str, main_theorem_types: List[str]) -> List[Theorem]:
    """
    Finds all theorem "bf-it" blocks: `{\bf <name>} {\it <body>}`

    Parameters
    ----------
    tex : str
        LaTeX source
    main_theorem_types : List[str]
        Possible theorem types

    Returns
    -------
    theorems : List[Theorem]
        List of parsed theorems
    """

    theorems: List[Theorem] = []
    pos = 0

    while True:
        bf_it_start_match = BF_IT_START_RE.search(tex, pos)
        if not bf_it_start_match:
            break

        start_body = bf_it_start_match.end()

        name = bf_it_start_match.group("name").strip()
        type_, ref, note = separate_name_segments(name, main_theorem_types)

        if type_ is None:
            pos = start_body
            continue 

        end_body = None

        brace_counter = 0
        for i in range(start_body, len(tex)):
            if tex[i] == "{":
                brace_counter += 1
            elif tex[i] == "}":
                brace_counter -= 1

                if brace_counter < 0:
                    end_body = i
                    break

        if not end_body:
            break

        body = tex[start_body:end_body].strip()

        theorems.append(
            {
                "type": type_,
                "ref": ref,
                "note": note,
                "body": body,
                "label": None,
            }
        )

        pos = end_body

    return theorems