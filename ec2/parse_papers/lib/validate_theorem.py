from ..types import Theorem
from typing import List

def _validate_type(theorem: Theorem, theorem_types: List[str]):
    if not theorem["type"] in theorem_types:
        raise ValueError(f"theorem has invalid type `{theorem['type']}`")
    
def _validate_body(theorem: Theorem):
    body = theorem["body"]

    dollar_sign_count = body.count("$")

    if len(body) < 32 and ("." not in body) and (dollar_sign_count == 0 or dollar_sign_count % 2 == 1):
        raise ValueError(f"theorem likely has truncated body `{body}`")

def validate_theorem(theorem: Theorem, theorem_types: List[str]):
    """
    Raises an error if the theorem is likely incorrectly parsed:
    - If type is not a valid theorem type
    - If body is likely truncated

    Parameters
    ----------
    theorem : Theorem
        Theorem to validate
    theorem_types : List[str]
        Possible theorem types
    """

    _validate_type(theorem, theorem_types)
    _validate_body(theorem)