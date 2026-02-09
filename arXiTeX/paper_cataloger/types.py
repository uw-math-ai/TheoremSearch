from pydantic import BaseModel
from typing import Optional, List

class Paper(BaseModel):
    id: str
    title: str
    license: Optional[str]
    authors: List[str]
    link: str
    abstract: str
    journal_ref: Optional[str]
    categories: List[str]
    citations: Optional[int]