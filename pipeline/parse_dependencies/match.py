import re
from typing import List, Dict, Any


def _find_location(body: str, proof: str, substring: str) -> str:
    if body and substring in body:
        return "body"
    if proof and substring in proof:
        return "proof"
    return "body"


def match_paper(statements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    statements: list sorted by ordinal ascending, each with keys:
        statement_id, body, proof, defines (list of {description, pattern}), uses (list of str)
    Returns dep rows ready for insertion into informal_dependency.
    """
    dep_rows = []
    recent_definer: Dict[str, tuple] = {}  # desc -> (a_id, compiled, pattern) — most recent wins
    used: set = set()  # (b_id, a_id) — one dep per pair

    for B in statements:
        b_id    = str(B["statement_id"])
        b_body  = B.get("body")  or ""
        b_proof = B.get("proof") or ""

        # Descriptions that B itself defines — uses of these are skipped because
        # B is re-introducing the notation, not depending on the prior definition.
        b_defines = {d.get("description", "") for d in B.get("defines", []) if d.get("description")}

        # Resolve uses against definitions from statements strictly before B
        # (recent_definer is updated with B's defines only after this loop).
        for use_str in B.get("uses", []):
            if not use_str:
                continue
            for desc, (a_id, compiled, dep_key) in recent_definer.items():
                if desc in b_defines:
                    continue
                key = (b_id, a_id)
                if key in used:
                    continue
                if compiled.search(use_str):
                    used.add(key)
                    dep_rows.append({
                        "src_id":   b_id,
                        "location": _find_location(b_body, b_proof, use_str),
                        "cite_id":  None,
                        "cite_key": None,
                        "dep_id":   a_id,
                        "dep_key":  use_str,
                        "dep_name": desc,
                        "methods":  ["llm"],
                    })

        # Update most-recent definer table with B's definitions.
        for define in B.get("defines", []):
            pattern = define.get("pattern", "").strip()
            desc    = define.get("description", "")
            if not pattern:
                continue
            try:
                compiled = re.compile(pattern)
            except re.error:
                try:
                    compiled = re.compile(re.escape(pattern))
                except re.error:
                    continue
            recent_definer[desc] = (b_id, compiled, pattern)

    return dep_rows
