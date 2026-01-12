from typing import Tuple, List
from .re_patterns import POTENTIAL_REF_RE

def separate_name_segments(name: str, main_theorem_types: List[str]) -> Tuple[str | None, str | None, str | None]:
    """
    Separates a theorem name into its segments: type, ref, and note.

    Parameters
    ----------
    name : str
        Theorem name
    main_theorem_types : List[str]
        Possible theorem types

    Returns
    -------
    type : str | None
        Theorem type, if it exists
    ref : str | None
        Theorem ref, if it exists
    note : str | None
        Theorem note, if it exists
    """
    
    name_segments = name.split()

    type_ = None
    ref = None
    note = None
    for segment in name_segments:
        segment_lower = segment.lower()

        if ref is None and POTENTIAL_REF_RE.match(segment):
            ref = segment
        elif note is None and segment.startswith("(") and segment.endswith(")"):
            note = segment.removeprefix("(").removesuffix(")").strip()
        elif type_ is None:
            for tt in main_theorem_types:
                if segment_lower in tt or tt in segment_lower:
                    type_ = tt
                    break
        else:
            break

    return type_, ref, note