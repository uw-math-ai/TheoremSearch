import json
import re

_JSON_RE = re.compile(r'\{.*\}', re.DOTALL)

# Minimum pattern length (post-strip) for a `defines` entry to be kept.
# Single-character patterns like "s", "C", "T" match almost anywhere in
# LaTeX (inside \sharp, \cdot, etc.) and produce massive false-positive
# cascades during connection.
MIN_PATTERN_LEN = 2


def parse_extraction(text: str) -> dict:
    m = _JSON_RE.search(text)
    if not m:
        return {"defines": [], "uses": []}
    try:
        obj = json.loads(m.group())
    except json.JSONDecodeError:
        return {"defines": [], "uses": []}
    defines = [
        d for d in obj.get("defines", [])
        if isinstance(d, dict)
        and isinstance(d.get("pattern"), str)
        and len(d["pattern"].strip()) >= MIN_PATTERN_LEN
    ]
    uses = [
        u for u in obj.get("uses", [])
        if isinstance(u, str) and u.strip()
    ]
    return {"defines": defines, "uses": uses}
