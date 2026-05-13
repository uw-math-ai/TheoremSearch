from datetime import datetime
from pydantic import BaseModel
from typing import Any, List, Literal, Optional


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


# Graph route models — minimal; use hydration endpoints for full content

class StatementNode(BaseModel):
    statement_id: str
    name: str                          # e.g. "Theorem 3.2"
    slogan: Optional[str] = None       # first slogan with insufficient_context = FALSE, if any exist
    depth: Optional[int] = None        # BFS depth from traversal origin; None for non-traversal endpoints


class DependencyEdge(BaseModel):
    src_id: str
    dep_id: Optional[str] = None       # resolved intrapaper target statement
    cite_id: Optional[str] = None      # resolved interpaper target paper
    cite_key: Optional[str] = None     # set for all interpaper deps
    dep_name: Optional[str] = None     # e.g. "Theorem 3.2" (LLM-extracted or stored)
    dep_key: Optional[str] = None      # verbatim phrase for LLM-only deps
    location: str
    methods: List[str]


class SubgraphResponse(BaseModel):
    nodes: List[StatementNode]
    edges: List[DependencyEdge]


# Hydration models

class IdsRequest(BaseModel):
    ids: List[str]


class StatementDetail(BaseModel):
    statement_id: str
    kind: str
    ref: Optional[str] = None
    body: str
    proof: Optional[str] = None
    note: Optional[str] = None
    paper_id: str
    paper_external_id: Optional[str] = None
    paper_title: Optional[str] = None


class PaperDetail(BaseModel):
    paper_id: str
    external_id: Optional[str] = None
    title: Optional[str] = None
    authors: List[str] = []
    abstract: Optional[str] = None
    url: Optional[str] = None
    source: Optional[str] = None


# /graph/paper response models. Every field below `paper_id` / `src_id` /
# `statement_id` is Optional so the response can shrink to `minimal` mode
# (paper_id+title only / statement_id+name only / src+cite+dep only) without
# carrying a wall of nulls — the routes set response_model_exclude_none=True.

GraphPaperItem = Literal["paper", "statements", "dependencies"]


class PaperItem(BaseModel):
    paper_id: str
    title: Optional[str] = None
    # Full mode — paper.* (minus preamble/bibliography/etc handled at SQL level):
    kind: Optional[str] = None
    source: Optional[str] = None
    authors: Optional[List[str]] = None
    url: Optional[str] = None
    external_id: Optional[str] = None
    categories: Optional[List[str]] = None
    updated_at: Optional[datetime] = None
    # arxiv_paper_metadata (excludes preamble, bibliography, bibtex,
    # in_validation, reference_ids, citation_count):
    abstract: Optional[str] = None
    journal_ref: Optional[str] = None
    doi: Optional[str] = None
    license: Optional[str] = None
    # lean_community_paper_metadata (excludes preamble, bibliography, bibtex):
    repo_slug: Optional[str] = None
    branch: Optional[str] = None
    src_path: Optional[str] = None


class StatementItem(BaseModel):
    statement_id: str
    name: str                          # e.g. "Theorem 3.2"
    # Full mode only:
    formality: Optional[str] = None
    note: Optional[str] = None
    body: Optional[str] = None
    proof: Optional[str] = None
    slogan: Optional[str] = None


class DependencyItem(BaseModel):
    src_id: str
    cite_id: Optional[str] = None
    dep_id: Optional[str] = None
    # Full mode only:
    cite_key: Optional[str] = None
    dep_key: Optional[str] = None
    dep_name: Optional[str] = None
    location: Optional[str] = None
    methods: Optional[List[str]] = None


class GraphPaperResponse(BaseModel):
    paper: Optional[PaperItem] = None
    statements: Optional[List[StatementItem]] = None
    dependencies: Optional[List[DependencyItem]] = None
