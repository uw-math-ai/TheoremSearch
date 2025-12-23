from typing import Set, Dict, List, Optional
import os
import io
import contextlib
import logging
from ..re_patterns import LABEL_RE
import pprint
from ..main_tex import get_main_tex_path
from plasTeX.TeX import TeX


def _silence_plastex_logging():
    for name in ("plasTeX", "plasTeX.TeX", "plasTeX.Packages"):
        logger = logging.getLogger(name)
        logger.setLevel(logging.CRITICAL)
        logger.propagate = False

def body_inner_latex(node) -> str:
    parts = []
    for child in getattr(node, "childNodes", []) or []:
        src = getattr(child, "source", None)
        if isinstance(src, str) and src.strip():
            parts.append(src.strip())
        else:
            # fallback: try textContent
            parts.append(getattr(child, "textContent", "") or "")
    return "".join(parts).strip()

def _get_node_label(doc, node) -> Optional[str]:
    # plasTeX stores labels in doc.context.labels: {label_string: target_node}
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
    main_tex_path = get_main_tex_path(src_dir)
    main_tex_name = os.path.basename(main_tex_path)

    old_cwd = os.getcwd()

    # if not debugging_mode:
    _silence_plastex_logging()

    tex = TeX()

    stderr_buf = io.StringIO()
    stdout_buf = io.StringIO()

    try:
        os.chdir(src_dir)

        cm = contextlib.nullcontext()
        if not debugging_mode:
            cm = contextlib.ExitStack()
            cm.enter_context(contextlib.redirect_stderr(stderr_buf))
            cm.enter_context(contextlib.redirect_stdout(stdout_buf))

        with cm:
            # Keep file handle open for the duration of parse()
            with open(main_tex_name, "r", encoding="utf-8", errors="ignore") as f:
                tex.input(f)
                doc = tex.parse()

        theorems: List[Dict] = []

        for env in sorted(theorem_types):
            if not env or any(ch.isspace() for ch in env):
                continue

            for node in doc.getElementsByTagName(env):

                label = _get_node_label(doc, node)
                number = node.ref.source

                body = body_inner_latex(node)
                body = LABEL_RE.sub("", body).strip()

                title = env.capitalize()
                name = f"{title} {number}{' (' + str(node.title.source) + ')' if node.title else ''}" if number else title

                theorems.append({
                    "paper_id": paper_id,
                    "name": name,
                    "label": label,
                    "body": body,
                })
                
        return theorems

    finally:
        os.chdir(old_cwd)
