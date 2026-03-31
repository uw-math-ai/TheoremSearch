from pydantic import BaseModel
from typing import List, Optional


DEFAULT_QUERY_PROMPT = "Instruct: Given an informal description of a mathematical result, retrieve the formal theorem statement that matches it. The query describes a specific theorem, lemma, or proposition from a research paper.\nQuery: "

class SearchRequest(BaseModel):
    query: str
    n_results: int = 10
    sources: List[str] = []
    authors: List[str] = []
    types: List[str] = []
    tags: List[str] = []
    paper_filter: Optional[str] = None
    year_range: Optional[List[int]] = None
    citation_range: Optional[List[int]] = None
    citation_weight: float = 0.0
    include_unknown_citations: bool = True
    prompt: Optional[str] = None
    db_top_k: Optional[int] = None


class PaperResult(BaseModel):
    paper_id: str
    source: str
    title: str
    authors: List[str]
    link: str
    summary: Optional[str] = None
    journal_ref: Optional[str] = None
    primary_category: Optional[str] = None
    categories: List[str] = []
    citations: Optional[int] = None
    year: Optional[int] = None
    journal_published: Optional[bool] = None


class TheoremResult(BaseModel):
    slogan_id: int
    theorem_id: int
    name: str
    body: str
    slogan: str
    theorem_type: str
    label: Optional[str] = None
    link: Optional[str] = None
    paper: PaperResult
    similarity: float
    score: float
    has_metadata: bool


class SearchResponse(BaseModel):
    theorems: List[TheoremResult]


# Graph route models

class StatementNode(BaseModel):
    statement_id: str
    formality: str
    kind: str
    body: str
    ref: Optional[str] = None
    label: Optional[str] = None
    decl_name: Optional[str] = None


class PaperNode(BaseModel):
    paper_id: str
    title: str
    external_id: Optional[str] = None
    source: Optional[str] = None
    url: Optional[str] = None


class DependencyEdge(BaseModel):
    kind: str
    interpaper: bool
    dep_name: Optional[str] = None
    dep_key: Optional[str] = None
    cite_key: Optional[str] = None
    tactic_context: Optional[str] = None
    source: StatementNode
    dep: Optional[StatementNode] = None
    dep_paper: Optional[PaperNode] = None


class GraphResponse(BaseModel):
    paper: PaperNode
    dependencies: List[DependencyEdge]
