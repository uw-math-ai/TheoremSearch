"""
Shared helpers for dependency parsing.
"""

import bisect
import json
import re

from typing import List, Tuple

# Anchor phrases with strength scores for the word-proximity heuristic.
_PROXIMITY_ANCHORS: List[Tuple[str, float]] = sorted([
    ("it follows",           1.0),
    ("as a consequence",     1.0),
    ("as a corollary",       1.0),
    ("by the above",         1.0),
    ("by the following",     1.0),
    ("follows from",         1.0),
    ("by the same argument", 0.9),
    ("previous result",      0.9),
    ("we conclude",          0.9),
    ("we deduce",            0.9),
    ("proved above",         0.9),
    ("the following",        0.9),
    ("the above",            0.9),
    ("follows",              1.0),
    ("consequence",          0.9),
    ("therefore",            0.9),
    ("whence",               0.9),
    ("hence",                0.9),
    ("preceding",            0.9),
    ("appealing to",         0.8),
    ("appeal to",            0.8),
    ("as established",       0.8),
    ("combined with",        0.8),
    ("recall that",          0.8),
    ("as before",            0.8),
    ("in view of",           0.8),
    ("in light of",          0.8),
    ("invoking",             0.8),
    ("invoke",               0.8),
    ("previous",             0.8),
    ("together with",        0.7),
    ("by analogy",           0.7),
    ("analogously",          0.7),
    ("thanks to",            0.7),
    ("recall",               0.7),
    ("following",            0.8),
    ("above",                0.7),
    ("below",                0.7),
    ("combining",            0.7),
    ("applying",             0.7),
    ("prior",                0.7),
    ("similarly",            0.6),
    ("immediately",          0.6),
    ("due to",               0.6),
    ("thus",                 0.5),
    ("using",                0.5),
    ("from",                 0.5),
    ("see",                  0.4),
    ("by",                   0.4),
    ("cf",                   0.4),
], key=lambda x: len(x[0]), reverse=True)


def _proximity_hits(text: str, cmd_start: int) -> List[Tuple[str, float]]:
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
    hits = _proximity_hits(text, cmd_start)
    return max((s for _, s in hits), default=0.0)


def proximity_keywords(text: str, cmd_start: int, threshold: float) -> str:
    qualified = list(dict.fromkeys(p for p, s in _proximity_hits(text, cmd_start) if s >= threshold))
    result = [p for p in qualified if not any(p != q and p in q for q in qualified)]
    return ",".join(result)


def max_anchor_strength(text: str) -> float:
    lower = text.lower()
    return max((s for p, s in _PROXIMITY_ANCHORS if p in lower), default=0.0)


def adjacent_keywords(text: str, threshold: float) -> str:
    lower = text.lower()
    qualified = list(dict.fromkeys(p for p, s in _PROXIMITY_ANCHORS if s >= threshold and p in lower))
    result = [p for p in qualified if not any(p != q and p in q for q in qualified)]
    return ",".join(result)


def strip_code_fence(text: str) -> str:
    if text.startswith("```"):
        text = re.sub(r"^```[^\n]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text.strip())
    return text


