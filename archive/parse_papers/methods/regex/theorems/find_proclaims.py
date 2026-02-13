from typing import List
from ....types import Theorem
from ....lib import separate_body_and_label
import re
from .separate_name_segments import separate_name_segments

PROCLAIM_RE = re.compile(r"\\proclaim\s*\{(?P<name>[^}]+)\}")
ENDPROCLAIM_RE = re.compile(r"\\endproclaim")

def find_proclaims(tex: str, main_theorem_types: List[str]) -> List[Theorem]:
    """
    Finds all theorem "proclaims": `\proclaim{<name>} ... \endproclaim`

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
        proclaim_match = PROCLAIM_RE.search(tex, pos)
        if not proclaim_match:
            break

        start_body = proclaim_match.end()

        name = proclaim_match.group("name").lstrip(r"\bf").strip()
        type_, ref, note = separate_name_segments(name, main_theorem_types)

        if type_ is None:
            pos = start_body
            continue

        end_proclaim_match = ENDPROCLAIM_RE.search(tex, start_body)
        if not end_proclaim_match:
            pos = start_body
            continue

        body_and_label = tex[start_body:end_proclaim_match.start()]
        body, label = separate_body_and_label(body_and_label)

        if body.startswith("{\\it"):
            body = body.removeprefix("{\\it").removesuffix("}")

        theorems.append(
            {
                "type": type_,
                "ref": ref,
                "note": note,
                "body": body,
                "label": label,
            }
        )

        pos = end_proclaim_match.end()

    return theorems