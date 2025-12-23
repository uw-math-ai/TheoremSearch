from typing import Set, Dict, List, Optional
import os
from ..re_patterns import LABEL_RE
from ..main_tex import get_main_tex_path
from plasTeX.TeX import TeX
from plasTeX.Logging import disableLogging
from ..tex_method.extract_from_tex import extract_envs_to_titles
from ..regex_method.flatten import flatten_tex

def body_inner_latex(node) -> str:
    parts = []
    for child in getattr(node, "childNodes", []) or []:
        src = getattr(child, "source", None)
        if isinstance(src, str) and src.strip():
            parts.append(src.strip())
        else:
            parts.append(getattr(child, "textContent", "") or "")
    return "".join(parts).strip()

def _get_node_label(doc, node) -> Optional[str]:
    try:
        labels = getattr(doc.context, "labels", {}) or {}
        for lab, target in labels.items():
            if target is node:
                return lab
    except Exception:
        pass
    return None

def parse_by_plastex(
    paper_id: str,
    src_dir: str,
    theorem_types: Set[str],
    debugging_mode: bool
) -> List[Dict]:
    envs_to_titles = extract_envs_to_titles(src_dir, theorem_types)

    main_tex_path = get_main_tex_path(src_dir)
    main_tex_name = os.path.basename(main_tex_path)

    old_cwd = os.getcwd()

    if not debugging_mode:
        disableLogging()

    tex = TeX()

    try:
        tex_str = flatten_tex(main_tex_name, src_dir)
        tex.input(tex_str)
        doc = tex.parse()

        theorems: List[Dict] = []

        for env in sorted(envs_to_titles.keys()):
            if not env or any(ch.isspace() for ch in env):
                continue

            for node in doc.getElementsByTagName(env):

                label = _get_node_label(doc, node)
                number = node.ref.source if node.ref else None

                body = body_inner_latex(node)
                body = LABEL_RE.sub("", body).strip()

                title = env.capitalize()
                name = " ".join(
                    item for item in [
                        title, 
                        number, 
                        f"({node.title.source})" if node.title else None
                    ]
                    if item is not None
                )

                theorems.append({
                    "paper_id": paper_id,
                    "name": name,
                    "label": label,
                    "body": body,
                })

        return theorems

    finally:
        os.chdir(old_cwd)
