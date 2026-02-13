from ..types import Theorem
from typing import List

def _validate_type(theorem: Theorem, main_theorem_types: List[str]):
    if not theorem["type"] in main_theorem_types:
        raise ValueError(f"Theorem has invalid type `{theorem['type']}`")
    
def _validate_body(theorem: Theorem):
    body = theorem["body"].strip().lower()

    if not body:
        raise ValueError("Empty theorem body")

    dollar_count = body.count("$")
    if dollar_count % 2 == 1:
        raise ValueError(f"Unbalanced math delimiters in `{body}`")

    if len(body) < 8:
        raise ValueError(f"Theorem body is too short `{body}`")

    if len(body) < 32 and not body.endswith(".") and dollar_count == 0:
        raise ValueError(f"Theorem likely has truncated body `{body}`")

    if body.endswith((
        " and", " or", "such that", " where", " let", " then", "for all", 
        "(", "[", "{", ",", ":", ";", "=", "<", "%")
    ):
        raise ValueError(f"Theorem likely truncated `{body}`")
    
def _validate_uniqueness(theorems: List[Theorem]):
    names = set()

    for theorem in theorems:
        name = " ".join(p for p in [
            theorem["type"].capitalize(),
            theorem["ref"],
            f"({theorem['note']})" if theorem["note"] else None
        ] if p is not None)

        if name in names:
            raise ValueError(f"Multiple theorems have the same name `{name}`")
        else:
            names.add(name)

def validate_theorem(theorem: Theorem, main_theorem_types: List[str]):
    """
    Raises an error if the theorem is likely incorrectly parsed:
    - If type is not a valid theorem type
    - If body is likely truncated

    Parameters
    ----------
    theorems : List[Theorem]
        Theorems to validate
    main_theorem_types : List[str]
        Possible theorem types
    """

    _validate_type(theorem, main_theorem_types)
    _validate_body(theorem)

def validate_theorems(theorems: List[Theorem], main_theorem_types: List[str]):
    """
    Raises an error if the theorems are likely incorrectly parsed:
    - If type is not a valid theorem type
    - If body is likely truncated
    - If name-conflicts exist

    Parameters
    ----------
    theorems : List[Theorem]
        Theorems to validate
    main_theorem_types : List[str]
        Possible theorem types
    """

    for theorem in theorems:
        validate_theorem(theorem, main_theorem_types)

    _validate_uniqueness(theorems)
    