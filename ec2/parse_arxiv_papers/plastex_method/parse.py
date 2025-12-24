from typing import Set, Dict, List, Optional
import io
import contextlib
import logging
import subprocess

from ..re_patterns import LABEL_RE, BEGIN_RE, END_RE
from ..main_tex import get_main_tex_path
from ..tex_method.extract_from_tex import extract_envs_to_titles

from plasTeX.TeX import TeX
from plasTeX.Logging import disableLogging

import os
import pprint


def _body_inner_latex(node) -> str:
    if hasattr(node, "source"):
        source = node.source
        source = LABEL_RE.sub("", source)

        if BEGIN_RE.match(source) and END_RE.match(source):
            source = BEGIN_RE.sub("", source, count=1)
            source = END_RE.sub("", source, count=1)

            return source.strip()
    
    return ""

def _get_node_label(doc, node) -> Optional[str]:
    try:
        labels = getattr(doc.context, "labels", {}) or {}
        for lab, target in labels.items():
            if target is node:
                return lab
    except Exception:
        pass
    return None


def _flatten_main_tex(main_tex_path: str, cwd: str) -> None:
    main_tex_path = os.path.abspath(main_tex_path)

    cmd = ["latex-flatten", main_tex_path, "--inplace"]
    r = subprocess.run(
        cmd,
        cwd=cwd,                         # <-- critical
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        r2 = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        raise RuntimeError(f"latex-flatten failed\nSTDOUT:\n{r2.stdout}\nSTDERR:\n{r2.stderr}")


@contextlib.contextmanager
def _silent_plastex(enabled: bool):
    """
    Silence plasTeX's logging and any accidental stdout/stderr writes.
    Keep it scoped so other processes aren't affected.
    """
    if not enabled:
        yield
        return

    # 1) disable plasTeX logging helper (works for many messages)
    disableLogging()

    # 2) also clamp python logging for known plasTeX loggers
    loggers = [
        "plasTeX",
        "plasTeX.TeX",
        "plasTeX.Packages",
        "plasTeX.DOM",
    ]
    prev_levels = {}
    for name in loggers:
        lg = logging.getLogger(name)
        prev_levels[name] = lg.level
        lg.setLevel(logging.CRITICAL)

    # 3) redirect any stray prints / writes
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            yield
        finally:
            for name in loggers:
                logging.getLogger(name).setLevel(prev_levels[name])


def parse_by_plastex(
    paper_id: str,
    src_dir: str,
    theorem_types: Set[str],
    debugging_mode: bool
) -> List[Dict]:
    envs_to_titles = extract_envs_to_titles(src_dir, theorem_types)

    main_tex_path = os.path.abspath(get_main_tex_path(src_dir))
    _flatten_main_tex(main_tex_path, cwd=os.path.dirname(main_tex_path))

    tex = TeX()

    silent = not debugging_mode

    try:
        theorems: List[Dict] = []

        with _silent_plastex(silent):
            with open(main_tex_path, "r", encoding="utf-8", errors="ignore") as f:
                tex.input(f.read())
            doc = tex.parse()

            for env in sorted(envs_to_titles.keys()):
                if not env or any(ch.isspace() for ch in env):
                    continue

                for node in doc.getElementsByTagName(env):
                    label = _get_node_label(doc, node)
                    number = node.ref.source if getattr(node, "ref", None) else None

                    body = _body_inner_latex(node)

                    title = None
                    if hasattr(node, "title") and node.title:
                        try:
                            title = node.title.source
                        except Exception:
                            title = str(node.title)

                    name = " ".join(
                        item for item in [
                            envs_to_titles[env],
                            number,
                            f"({title})" if title else None,
                        ]
                        if item
                    )

                    if body and name:
                        theorems.append({
                            "paper_id": paper_id,
                            "name": name,
                            "label": label,
                            "body": body,
                        })

        #pprint.pprint(theorems)
        return theorems

    except Exception as e:
        # raise e
        return []