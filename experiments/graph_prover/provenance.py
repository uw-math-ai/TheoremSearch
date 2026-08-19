"""Core record types for the graph_prover experiment.

Every premise carries a provenance tag from the retrieval step that first surfaced it,
every attempt records exactly what was offered / used / spent, and one TaskRecord per
(task, arm) is appended to results/<run_id>/<arm>.jsonl. This is what turns a solved
task into an auditable literature-to-verified-proof trace instead of a bare success bit.

Provenance tag grammar (string, human-greppable):
  cosine#<rank>                       arm A seed
  graph:<edge_type>-parent-of:<name>  arm B typed one-hop expansion
  xform:anchor=<informal stmt id>     arm C informal->formal jump
  trigram:<query>                     mutation 1 (unknown-identifier repair)
  error-requery#<rank>                mutation 2
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field


@dataclass
class CompileResult:
    compiles: bool
    sorry_free: bool
    axioms: list[str] = field(default_factory=list)
    used_constants: list[str] = field(default_factory=list)
    used_constants_source: str = "none"   # "kernel" | "string-match" | "none"
    errors: list[dict] = field(default_factory=list)  # {line, col, message}
    forbidden_used: list[str] = field(default_factory=list)
    wall_time_s: float = 0.0
    raw_tail: str = ""                    # last ~2k chars of lake output, for debugging

    @property
    def solved(self) -> bool:
        return self.compiles and self.sorry_free and not self.forbidden_used


@dataclass
class Candidate:
    statement_id: str
    decl_name: str
    sig: str = ""
    score: float = 0.0
    provenance: str = ""


@dataclass
class RetrievalStep:
    attempt_idx: int
    query_kind: str                       # slogan-vec | error-text | trigram | ...
    query_text: str = ""
    seeds: list[str] = field(default_factory=list)
    edges_traversed: list[tuple[str, str, str]] = field(default_factory=list)  # src, edge_type, dst
    cross_links: list[tuple[str, str]] = field(default_factory=list)  # informal anchor id, decl
    candidates: list[Candidate] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    mutation_op: str | None = None


@dataclass
class Attempt:
    idx: int
    premises_offered: list[Candidate] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    plan_text: str = ""
    proof_text: str = ""
    compile: CompileResult | None = None
    premises_used: list[str] = field(default_factory=list)  # offered ∩ used_constants
    branch: str = ""                      # arm E: which beam branch produced this


@dataclass
class TaskRecord:
    tid: str
    decl_name: str
    arm: str
    steps: list[RetrievalStep] = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)
    solved: bool = False
    total_cost_usd: float = 0.0
    wall_time_s: float = 0.0
    error: str = ""                       # orchestrator-level failure, if any

    def to_json(self) -> str:
        return json.dumps(dataclasses.asdict(self), ensure_ascii=False)


def task_record_from_json(line: str) -> dict:
    """Read side stays plain dicts — score.py only aggregates."""
    return json.loads(line)
