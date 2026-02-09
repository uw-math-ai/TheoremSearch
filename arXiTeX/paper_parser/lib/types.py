from enum import Enum

class ParsingMethod(Enum):
    """
    Methods for attempting to parse theorems from a LaTeX source. Supported: PlasTeX, TeX, and
    Regex.
    """

    PlasTeX = "plasTeX"
    TeX = "TeX"
    Regex = "regex"

class TheoremValidationLevel(Enum):
    """
    Level to check if parsed theorems are valid.
    """

    Theorem = "theorem"
    Paper = "paper"