from ...types import Theorem, TheoremType
from typing import List

def _validate_type(theorem: Theorem):
    if not theorem.type in [t.value for t in TheoremType]:
        raise ValueError(f"Theorem has invalid type: `{theorem.type}`")
    
def _validate_ref(theorem: Theorem):
    if not theorem.ref:
        raise ValueError(f"Theorem has no ref")
    
def _validate_body(theorem: Theorem):
    body = theorem.body.lower().strip()

    if not body:
        raise ValueError("Empty theorem body")

    dollar_count = body.count("$")
    if dollar_count % 2 == 1:
        raise ValueError(f"Theorem body has unbalanced math delimiters: `{body}`")

    if len(body) < 8:
        raise ValueError(f"Theorem body is too short: `{body}`")

    if len(body) < 32 and not body.endswith(".") and dollar_count == 0:
        raise ValueError(f"Theorem body is likely truncated: `{body}`")

    if body.endswith((
        " and", " or", "such that", " where", " let", " then", "for all", 
        "(", "[", "{", ",", ":", ";", "=", "<", "%")
    ):
        raise ValueError(f"Theorem body is likely truncated: `{body}`")
    
def _validate_proof(theorem: Theorem):
    if theorem.proof is None:
        return

    proof = theorem.proof.lower().strip()

    if not proof:
        raise ValueError("Empty theorem proof")

    dollar_count = proof.count("$")
    if dollar_count % 2 == 1:
        raise ValueError(f"Theorem proof has unbalanced math delimiters: `{proof}`")

    if len(proof) < 8:
        raise ValueError(f"Theorem proof is too short: `{proof}`")

    if len(proof) < 32 and not proof.endswith(".") and dollar_count == 0:
        raise ValueError(f"Theorem proof is likely truncated: `{proof}`")

    if proof.endswith((
        " and", " or", "such that", " where", " let", " then", "for all", 
        "(", "[", "{", ",", ":", ";", "=", "<", "%")
    ):
        raise ValueError(f"Theorem proof is likely truncated: `{proof}`")
    
def _validate_uniqueness(theorems: List[Theorem]):
    names = set()

    for theorem in theorems:
        name = " ".join(p for p in [
            theorem.type.capitalize(),
            theorem.ref,
            f"({theorem.note})" if theorem.note else None
        ] if p is not None)

        if name in names:
            raise ValueError(f"Multiple theorems have the same name `{name}`")
        else:
            names.add(name)

def validate_theorem(theorem: Theorem):
    """
    Raises an error if the theorem is likely incorrectly parsed:
    - If type is not a valid theorem type
    - If there is no ref
    - If body is likely truncated
    - If proof is likely truncated (if it exists)

    Parameters
    ----------
    theorems : List[Theorem]
        Theorems to validate
    """

    _validate_type(theorem)
    _validate_ref(theorem)
    _validate_body(theorem)
    _validate_proof(theorem)

def validate_theorems(theorems: List[Theorem]):
    """
    Raises an error if the theorems are likely incorrectly parsed:
    - If type is not a valid theorem type
    - If body is likely truncated
    - If name-conflicts exist

    Parameters
    ----------
    theorems : List[Theorem]
        Theorems to validate
    """

    for theorem in theorems:
        validate_theorem(theorem)

    _validate_uniqueness(theorems)
    