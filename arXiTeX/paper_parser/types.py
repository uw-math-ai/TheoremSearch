from pydantic import BaseModel
from enum import Enum
from typing import Optional

class TheoremType(str, Enum):
    Theorem = "theorem"
    Lemma = "lemma"
    Corollary = "corollary"
    Proposition = "proposition"

class Theorem(BaseModel):
    type: TheoremType
    ref: Optional[str] = None
    note: Optional[str] = None
    label: Optional[str] = None
    body: str
    proof: Optional[str] = None