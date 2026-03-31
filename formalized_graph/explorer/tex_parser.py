from __future__ import annotations

import os
import re
from typing import Any, Dict, List

LABEL_RE = re.compile(r"\\label\{([\w.:-]+)\}")
LEAN_RE = re.compile(r"\\lean\{([\w.:\']+)\}")
USES_RE = re.compile(r"\\uses\{([\w.,\s:-]+)\}")


def parse_tex_file(file_path: str, base_dir: str) -> List[Dict[str, Any]]:
    with open(file_path, encoding="utf-8") as f:
        content = f.read()
    rel_path = os.path.relpath(file_path, base_dir)
    nodes: List[Dict[str, Any]] = []

    # Match theorem-like environments
    pattern = r"(.*?)\\begin\{([a-z]+)\}(?:\[(.*?)\])?(.*?)\\end\{\2\}"

    for match in re.finditer(pattern, content, re.DOTALL | re.IGNORECASE):
        pre_text = match.group(1)
        env_type = match.group(2).lower()
        title = match.group(3) if match.group(3) else ""
        body_content = match.group(4)

        if env_type not in [
            "theorem",
            "lemma",
            "definition",
            "corollary",
            "proposition",
            "remark",
        ]:
            continue

        # ORDER INDEPENDENCE: Search for label and lean tags anywhere in the body
        label_m = LABEL_RE.search(body_content)
        lean_m = LEAN_RE.search(body_content)
        uses_m = USES_RE.search(body_content)
        
        # If no label, we use the Lean name as a backup ID
        label = label_m.group(1) if label_m else (lean_m.group(1) if lean_m else None)
        if not label:
            continue

        # Clean Body: remove the metadata tags for rendering
        clean_body = body_content
        clean_body = LABEL_RE.sub("", clean_body)
        clean_body = LEAN_RE.sub("", clean_body)
        clean_body = USES_RE.sub("", clean_body)
        clean_body = re.sub(r"\\leanok|\\discussion\{.*?\}", "", clean_body)
        clean_body = re.sub(r"\s+", " ", clean_body).strip()

        # Context Look-behind
        context = ""
        if pre_text:
            paras = re.split(r"\n\s*\n", pre_text)
            context = paras[-1].strip()
            context = re.sub(r"\\label\{.*?\}|\\lean\{.*?\}|\\uses\{.*?\}", "", context)
            context = re.sub(r"\s+", " ", context).strip()
            if len(context) > 500:
                context = "..." + context[-500:]

        nodes.append(
            {
                "id": label,
                "type": env_type,
                "title": title,
                "body": clean_body,
                "context": context,
                "lean_name": lean_m.group(1) if lean_m else None,
                "uses": [u.strip() for u in uses_m.group(1).split(",")]
                if uses_m
                else [],
                "file": rel_path,
            }
        )
    return nodes


def build_paper_graph(root_dir: str) -> Dict[str, Any]:
    paper_nodes: Dict[str, Any] = {}
    if not os.path.exists(root_dir):
        return {}
    for root, _dirs, files in os.walk(root_dir):
        for file in files:
            if file.endswith(".tex"):
                nodes = parse_tex_file(os.path.join(root, file), root_dir)
                for node in nodes:
                    paper_nodes[node["id"]] = node
    return paper_nodes
