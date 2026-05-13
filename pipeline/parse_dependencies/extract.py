import json
import re

_JSON_ARRAY_RE = re.compile(r'\[.*\]', re.DOTALL)

# Minimum pattern length (post-strip) for a `defines` entry to be kept.
# Single-character patterns like "s", "C", "T" match almost anywhere in
# LaTeX (inside \sharp, \cdot, etc.) and produce massive false-positive
# cascades during connection.
MIN_PATTERN_LEN = 2


def _clean_extraction(obj) -> dict:
    if not isinstance(obj, dict):
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


def parse_extraction_batch(text: str, expected_ids: list[str]) -> dict[str, dict]:
    """
    Parse the LLM's response to a batched notation prompt. Expects a JSON
    array of ``{"id", "defines", "uses"}`` objects; each ``id`` is matched
    against ``expected_ids`` so order doesn't matter and entries with unknown
    or missing ids are dropped.

    Returns a dict ``{id: {"defines": [...], "uses": [...]}}`` containing
    exactly the ids the model returned that we asked for. Statements absent
    from this dict were not extracted (malformed item, missing id, etc.) and
    callers should count them as failed.
    """
    m = _JSON_ARRAY_RE.search(text)
    if not m:
        return {}
    try:
        arr = json.loads(m.group())
    except json.JSONDecodeError:
        return {}
    if not isinstance(arr, list):
        return {}
    wanted = set(expected_ids)
    out: dict[str, dict] = {}
    for obj in arr:
        if not isinstance(obj, dict):
            continue
        sid = obj.get("id")
        if not isinstance(sid, str) or sid not in wanted or sid in out:
            continue
        out[sid] = _clean_extraction(obj)
    return out
