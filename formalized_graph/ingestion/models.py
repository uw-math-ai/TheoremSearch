from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class EntityKind(Enum):
    THEOREM = "theorem"
    LEMMA = "lemma"
    DEFINITION = "definition"
    AXIOM = "axiom"
    UNKNOWN = "unknown"


@dataclass
class VerifiedPremise:
    full_name: str
    kind: EntityKind
    file_path: Path
    module: str
    docstring: str | None = None
    code_statement: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "full_name": self.full_name,
            "kind": self.kind.value,
            "file_path": str(self.file_path),
            "module": self.module,
            "docstring": self.docstring,
            "code_statement": self.code_statement,
        }


@dataclass
class VerifiedDependency:
    source_name: str
    target_name: str
    is_implicit: bool = False  # True if found inside a tactic like 'simp'
    tactic_context: (
        str | None
    ) = None  # The specific tactic that triggered this link
