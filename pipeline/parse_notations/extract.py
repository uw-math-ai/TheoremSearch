import json
import re

_JSON_RE = re.compile(r'\{.*\}', re.DOTALL)


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
        if isinstance(d, dict) and isinstance(d.get("pattern"), str) and d["pattern"].strip()
    ]
    uses = [
        u for u in obj.get("uses", [])
        if isinstance(u, str) and u.strip()
    ]
    return {"defines": defines, "uses": uses}
