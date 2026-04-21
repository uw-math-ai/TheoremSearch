"""
Shared helpers for LLM-based dependency parsing.

Used by both the inline path (interpaper.py, intrapaper.py)
and the batch connect path (batch/connect.py).
"""

import bisect
import re

import yaml
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from ..constants import STATEMENT_KINDS

_VALID_LOCATIONS = frozenset(("body", "note", "proof", "pre_context", "post_context"))
_INTER_LOCATIONS = frozenset(("pre_context", "post_context"))
_LOCATION_RANK = {"body": 1, "proof": 2, "note": 3, "pre_context": 4, "post_context": 5}

# Anchor phrases with strength scores for the word-proximity heuristic.
# Sorted longest-first so multi-word phrases are matched before their sub-words.
_PROXIMITY_ANCHORS: List[Tuple[str, float]] = sorted([
    ("it follows",       1.0),
    ("as a consequence", 1.0),
    ("as a corollary",   1.0),
    ("by the above",     1.0),
    ("by the following", 1.0),
    ("previous result",  0.9),
    ("the following",    0.9),
    ("the above",        0.9),
    ("follows",          1.0),
    ("consequence",      0.9),
    ("therefore",        0.9),
    ("hence",            0.9),
    ("thus",             0.5),
    ("preceding",        0.9),
    ("previous",         0.8),
    ("following",        0.8),
    ("above",            0.7),
    ("below",            0.7),
    ("combining",        0.7),
    ("applying",         0.7),
    ("prior",            0.7),
    ("using",            0.5),
], key=lambda x: len(x[0]), reverse=True)


def _proximity_hits(text: str, cmd_start: int) -> List[Tuple[str, float]]:
    """Return (phrase, score) for every anchor occurrence, where score = strength / word_distance."""
    word_starts = [m.start() for m in re.finditer(r'\S+', text)]
    if not word_starts:
        return []
    cmd_word = bisect.bisect_left(word_starts, cmd_start)
    lower = text.lower()
    hits: List[Tuple[str, float]] = []
    for phrase, strength in _PROXIMITY_ANCHORS:
        idx = 0
        while True:
            pos = lower.find(phrase, idx)
            if pos < 0:
                break
            anchor_word = bisect.bisect_left(word_starts, pos)
            dist = abs(anchor_word - cmd_word)
            hits.append((phrase, strength / max(1, dist)))
            idx = pos + len(phrase)
    return hits


def proximity_score(text: str, cmd_start: int) -> float:
    """Return max(strength / word_distance) over all anchor occurrences near cmd_start."""
    hits = _proximity_hits(text, cmd_start)
    return max((s for _, s in hits), default=0.0)


def proximity_keywords(text: str, cmd_start: int, threshold: float) -> str:
    """Return a '|'-delimited string of distinct anchor phrases that individually score >= threshold.

    Shorter phrases that are substrings of a longer matched phrase are suppressed.
    Used as dep_key for heuristic \\ref/\\cite rows.
    """
    qualified = list(dict.fromkeys(p for p, s in _proximity_hits(text, cmd_start) if s >= threshold))
    result = [p for p in qualified if not any(p != q and p in q for q in qualified)]
    return "|".join(result)


def max_anchor_strength(text: str) -> float:
    """Return the max strength of any anchor phrase found in text (no distance weighting).

    Used for adjacent-statement heuristic where there is no explicit \\ref/\\cite.
    """
    lower = text.lower()
    return max((s for p, s in _PROXIMITY_ANCHORS if p in lower), default=0.0)


def adjacent_keywords(text: str, threshold: float) -> str:
    """Return a '|'-delimited string of anchor phrases with strength >= threshold.

    Shorter phrases that are substrings of a longer matched phrase are suppressed.
    Used as dep_key for adjacent-statement heuristic rows.
    """
    lower = text.lower()
    qualified = list(dict.fromkeys(p for p, s in _PROXIMITY_ANCHORS if s >= threshold and p in lower))
    result = [p for p in qualified if not any(p != q and p in q for q in qualified)]
    return "|".join(result)


def dedup_dep_rows(rows: List[Dict]) -> List[Dict]:
    """Deduplicate rows by (src_id, dep_id), keeping best location and dep_key.

    Location preference: body > proof > note > pre_context > post_context.
    dep_key preference: non-None over None (deterministic labels beat LLM phrases only
    when used together in _merge; here we just keep the best-location row's dep_key).
    """
    best: Dict[tuple, Dict] = {}
    for r in rows:
        key = (r["src_id"], r["dep_id"])
        if key not in best:
            best[key] = r
        else:
            cur_rank = _LOCATION_RANK.get(best[key]["location"], 99)
            new_rank = _LOCATION_RANK.get(r["location"], 99)
            if new_rank < cur_rank:
                best[key] = r
    return list(best.values())

_KINDS_RE = "|".join(re.escape(k) for k in sorted(STATEMENT_KINDS, key=len, reverse=True))
_DEP_NAME_RE = re.compile(rf"^({_KINDS_RE})\s+([\w.]+)$", re.IGNORECASE)


def strip_code_fence(text: str) -> str:
    if text.startswith("```"):
        text = re.sub(r"^```[^\n]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text.strip())
    return text


def build_stmt_id_map(statements: List[Dict]) -> Dict[str, str]:
    """Return {display_label → statement_id} using the same scheme as batch/prepare.py."""
    used: Dict[str, int] = {}
    result: Dict[str, str] = {}
    for i, s in enumerate(statements):
        base = s.get("ref") or f"{s['kind'].capitalize()} {i + 1}"
        if base in used:
            used[base] += 1
            label = f"{base} ({used[base]})"
        else:
            used[base] = 0
            label = base
        result[label] = s["statement_id"]
    return result


def parse_dep_name(dep_name: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """'Theorem 3.2' → ('theorem', '3.2'). Returns (None, None) if unrecognized."""
    if not dep_name:
        return None, None
    m = _DEP_NAME_RE.match(dep_name.strip())
    return (m.group(1).lower(), m.group(2)) if m else (None, None)


def parse_inter_llm_text(
    text: str,
    bib: Dict[str, Dict],
    id_to_statement_id: Dict[str, str],
) -> Optional[Dict[str, list]]:
    """Parse LLM inter-paper response → {stmt_id: [citation tuples]}. Returns None on error."""
    try:
        data = yaml.safe_load(strip_code_fence(text.strip()))
        citations = data.get("citations", []) if data else []
    except Exception:
        return None

    statement_cites: Dict[str, list] = defaultdict(list)
    seen: set = set()

    for c in citations:
        src_label = c.get("src", "").strip()
        cite_key  = c.get("cite_key", "").strip()
        dep_name  = c.get("dep_name") or None
        location  = c.get("location", "").strip()
        phrase    = c.get("phrase") or None

        if location not in _INTER_LOCATIONS or cite_key not in bib:
            continue
        stmt_id = id_to_statement_id.get(src_label)
        if not stmt_id:
            continue

        theorem_type, theorem_ref = parse_dep_name(dep_name)
        key = (stmt_id, cite_key, theorem_ref, location)
        if key in seen:
            continue
        seen.add(key)
        statement_cites[stmt_id].append((cite_key, theorem_type, theorem_ref, location, phrase))

    return statement_cites


def parse_combined_llm_text(
    text: str,
    bib: Dict[str, Dict],
    id_to_statement_id: Dict[str, str],
) -> Optional[Tuple[List[dict], Dict[str, list]]]:
    """Parse combined LLM response → (intra_rows, inter_statement_cites). Returns None on error."""
    try:
        data = yaml.safe_load(strip_code_fence(text.strip())) or {}
    except Exception:
        return None

    # --- intra: each entry is [src_id, dep_id, location, key?] ---
    rows = []
    seen_intra: set = set()
    for entry in (data.get("deps") or []):
        if not isinstance(entry, (list, tuple)) or len(entry) < 3:
            continue
        src_label, dep_label, location = str(entry[0]).strip(), str(entry[1]).strip(), str(entry[2]).strip()
        dep_key = str(entry[3]).strip() if len(entry) > 3 and entry[3] not in (None, "") else None
        if location not in _VALID_LOCATIONS:
            continue
        src_id = id_to_statement_id.get(src_label)
        dep_id = id_to_statement_id.get(dep_label)
        if not src_id or not dep_id or src_id == dep_id:
            continue
        key = (src_id, dep_id, location)
        if key in seen_intra:
            continue
        seen_intra.add(key)
        rows.append({
            "src_id":   src_id,
            "location": location,
            "cite_id":  None,
            "cite_key": None,
            "dep_id":   dep_id,
            "dep_key":  dep_key,
            "dep_name": None,
        })
    intra_rows = dedup_dep_rows(rows)

    # --- inter: each entry is [src_id, cite_key, dep_name_or_null, location, key?] ---
    statement_cites: Dict[str, list] = defaultdict(list)
    seen_inter: set = set()
    for entry in (data.get("cites") or []):
        if not isinstance(entry, (list, tuple)) or len(entry) < 4:
            continue
        src_label = str(entry[0]).strip()
        cite_key  = str(entry[1]).strip()
        dep_name  = entry[2] if entry[2] not in (None, "null", "~", "") else None
        location  = str(entry[3]).strip()
        phrase    = str(entry[4]).strip() if len(entry) > 4 and entry[4] not in (None, "") else None
        if location not in _INTER_LOCATIONS or cite_key not in bib:
            continue
        stmt_id = id_to_statement_id.get(src_label)
        if not stmt_id:
            continue
        theorem_type, theorem_ref = parse_dep_name(dep_name)
        key = (stmt_id, cite_key, theorem_ref, location)
        if key in seen_inter:
            continue
        seen_inter.add(key)
        statement_cites[stmt_id].append((cite_key, theorem_type, theorem_ref, location, phrase))

    return intra_rows, statement_cites


def parse_intra_llm_text(
    text: str,
    id_to_statement_id: Dict[str, str],
) -> Optional[List[dict]]:
    """Parse LLM intra-paper response → list of dep rows. Returns None on error."""
    try:
        data = yaml.safe_load(strip_code_fence(text.strip()))
        deps = data.get("dependencies", []) if data else []
    except Exception:
        return None

    rows = []
    seen = set()
    for dep in deps:
        src_label = dep.get("src", "").strip()
        dep_label = dep.get("dep", "").strip()
        location  = dep.get("location", "").strip()

        if location not in _VALID_LOCATIONS:
            continue
        src_stmt_id = id_to_statement_id.get(src_label)
        dep_stmt_id = id_to_statement_id.get(dep_label)
        if not src_stmt_id or not dep_stmt_id or src_stmt_id == dep_stmt_id:
            continue

        key = (src_stmt_id, dep_stmt_id, location)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "src_id":   src_stmt_id,
            "location": location,
            "cite_id":  None,
            "cite_key": None,
            "dep_id":   dep_stmt_id,
            "dep_key":  dep.get("phrase") or None,
            "dep_name": None,
        })
    return dedup_dep_rows(rows)
