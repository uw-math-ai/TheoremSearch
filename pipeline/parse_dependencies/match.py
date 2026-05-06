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
    first_definer: Dict[str, tuple] = {}  # desc -> (a_id, compiled, pattern)
    used: set = set()  # (b_id, a_id, desc)

    for j, B in enumerate(statements):
        b_id = str(B["statement_id"])
        b_body  = B.get("body")  or ""
        b_proof = B.get("proof") or ""

        for define in B.get("defines", []):
            pattern = define.get("pattern", "").strip()
            desc    = define.get("description", "")
            if not pattern or desc in first_definer:
                continue
            try:
                compiled = re.compile(pattern)
            except re.error:
                try:
                    compiled = re.compile(re.escape(pattern))
                except re.error:
                    continue
            first_definer[desc] = (b_id, compiled, pattern)

        for use_str in B.get("uses", []):
            if not use_str:
                continue
            for desc, (a_id, compiled, dep_key) in first_definer.items():
                if a_id == b_id:
                    continue
                key = (b_id, a_id, desc)
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

    return dep_rows
