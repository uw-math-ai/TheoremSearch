import os
from dataclasses import dataclass
from typing import Optional, Dict, Set, List
from .re_patterns import (
    INPUT_RE,
    DOC_CLASS_RE,
    SECTION_LIKE_RE,
    THEOREM_ENV_RE,
    CITE_RE
)

@dataclass
class TexCandidate:
    path: str
    rel_path: str
    content: str
    included_by: Set[str]
    includes: Set[str]

def _read_file(path: str) -> str:
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")

def _find_tex_files(root: str) -> Dict[str, TexCandidate]:
    candidates: Dict[str, TexCandidate] = {}

    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if not fn.endswith(".tex"):
                continue
            full_path = os.path.join(dirpath, fn)
            rel_path = os.path.relpath(full_path, root)
            content = _read_file(full_path)
            candidates[rel_path] = TexCandidate(
                path=full_path,
                rel_path=rel_path,
                content=content,
                included_by=set(),
                includes=set()
            )
    return candidates

def _resolve_include(base_rel: str, target: str) -> str:
    # target might be "foo", "./foo", "subdir/foo", with or without .tex
    # we resolve relative to base_rel’s directory
    base_dir = os.path.dirname(base_rel)
    if not target.endswith(".tex"):
        target_tex = target + ".tex"
    else:
        target_tex = target
    return os.path.normpath(os.path.join(base_dir, target_tex))

def _build_inclusion_graph(candidates: Dict[str, TexCandidate]) -> None:
    for rel_path, cand in candidates.items():
        for m in INPUT_RE.finditer(cand.content):
            target = m.group(2).strip()
            resolved = _resolve_include(rel_path, target)
            if resolved in candidates:
                cand.includes.add(resolved)
                candidates[resolved].included_by.add(rel_path)

def _has_documentclass(cand: TexCandidate) -> bool:
    return bool(DOC_CLASS_RE.search(cand.content))

def _score_candidate(cand: TexCandidate) -> float:
    c = cand.content
    score = 0.0

    # Basic structure
    if "\\begin{document}" in c:
        score += 3.0
    if "\\end{document}" in c:
        score += 3.0

    # Title/author/abstract
    if "\\title" in c:
        score += 2.0
    if "\\author" in c:
        score += 2.0
    if "\\maketitle" in c:
        score += 2.0
    if "\\begin{abstract}" in c:
        score += 2.0

    # Section/theorem/citations
    score += 0.5 * len(SECTION_LIKE_RE.findall(c))
    score += 0.5 * len(THEOREM_ENV_RE.findall(c))
    score += 0.2 * len(CITE_RE.findall(c))

    # Length heuristic
    lines = c.count("\n")
    score += min(lines / 200.0, 5.0)  # cap contribution

    # Penalties for likely-non-main
    lower_name = os.path.basename(cand.rel_path).lower()
    docclass_m = DOC_CLASS_RE.search(c)

    if docclass_m and "beamer" in docclass_m.group(0):
        score -= 5.0

    if any(w in lower_name for w in ("draft", "notes", "slides", "talk", "reply", "response")):
        score -= 3.0

    lower = c.lower()

    if "response to referee" in lower or "reply to referee" in lower:
        score -= 5.0

    # --- NEW: strong penalties for draft / TODO markers in the content ---

    # Macros typically used in draft mode
    draft_macros = [
        r"\fixme", r"\FIXME",
        r"\todo", r"\TODO",
        r"\todoin", r"\todo[",  # todonotes variants
        r"\missingfigure",      # from todonotes
        r"\XXX", r"\xx", r"\xxx"
    ]
    if any(macro in c for macro in draft_macros):
        score -= 8.0  # strong penalty if any draft macro appears

    # Obvious inline TODO markers
    draft_tokens = [
        "TODO", "TBD", "FIXME",
        "xxx", "XXX",
        "fill in", "to be completed", "to be filled"
    ]
    if any(tok.lower() in lower for tok in draft_tokens):
        score -= 4.0

    # draft option in documentclass (e.g. \documentclass[draft]{article})
    if docclass_m and "draft" in docclass_m.group(0).lower():
        score -= 4.0

    return score

def get_main_tex_path(source_dir: str) -> Optional[str]:
    """
    Heuristic main .tex finder:
    - Build inclusion graph
    - Take .tex with \\documentclass that are not included by others as root candidates
    - If multiple, score them and pick the best
    """
    candidates = _find_tex_files(source_dir)
    if not candidates:
        return None

    _build_inclusion_graph(candidates)

    docclass_files = {
        rel_path: cand
        for rel_path, cand in candidates.items()
        if _has_documentclass(cand)
    }

    if not docclass_files:
        return None

    # Roots = documentclass files not included by any other
    roots: List[TexCandidate] = [
        cand for cand in docclass_files.values() if not cand.included_by
    ]

    if not roots:
        # Fallback: consider all docclass files
        roots = list(docclass_files.values())

    if len(roots) == 1:
        return roots[0].path

    # Score and pick best
    best_cand = max(roots, key=_score_candidate)
    return best_cand.path