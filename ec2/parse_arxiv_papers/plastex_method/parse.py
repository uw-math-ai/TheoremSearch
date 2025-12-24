from typing import Set, Dict, List, Optional
import io
import contextlib
import logging
import os

from ..re_patterns import LABEL_RE
from ..main_tex import get_main_tex_path
from ..tex_method.extract_from_tex import extract_envs_to_titles

from plasTeX.TeX import TeX
from plasTeX.Logging import disableLogging

import pprint

def _get_node_body(node) -> str:
    parts = []
    for child in getattr(node, "childNodes", []) or []:
        src = getattr(child, "source", None)
        if isinstance(src, str) and src.strip():
            parts.append(src.strip())
        else:
            parts.append(child.textContent)
    return LABEL_RE.sub("", "".join(parts).strip(), count=1).strip()


def _get_node_label(doc, node) -> Optional[str]:
    try:
        labels = getattr(doc.context, "labels", {}) or {}
        for lab, target in labels.items():
            if target is node and isinstance(lab, str) and "plasTeX" not in lab:
                return lab
    except Exception:
        pass
    return None


def _get_node_name(node, title) -> str:
    number = node.ref.source if getattr(node, "ref", None) else None

    note = None
    if hasattr(node, "title") and node.title:
        try:
            note = node.title.source
        except Exception:
            note = str(node.title)

    return " ".join(
        item for item in [title, number, f"({note})" if note else None]
        if item
    )


@contextlib.contextmanager
def _silent_plastex(enabled: bool):
    if not enabled:
        yield
        return

    disableLogging()

    loggers = ["plasTeX", "plasTeX.TeX", "plasTeX.Packages", "plasTeX.DOM"]
    prev_levels = {}
    for name in loggers:
        lg = logging.getLogger(name)
        prev_levels[name] = lg.level
        lg.setLevel(logging.CRITICAL)

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            yield
        finally:
            for name in loggers:
                logging.getLogger(name).setLevel(prev_levels[name])


@contextlib.contextmanager
def _with_texinputs(src_dir: str, main_dir: str):
    """
    Make TeX file lookup prefer local project files (no TeXLive required).
    We include both main_dir and src_dir, plus recursive search ("//") which
    helps when packages/macros live in subfolders.
    """
    old = os.environ.get("TEXINPUTS")
    sep = os.pathsep

    # TeX supports "dir//" meaning "search dir recursively"
    # Keep both non-recursive and recursive; some resolvers treat them differently.
    entries = [
        main_dir, main_dir + "//",
        src_dir,  src_dir + "//",
        ".", "./",
    ]

    prefix = sep.join(entries) + sep
    os.environ["TEXINPUTS"] = prefix + (old or "")

    try:
        yield
    finally:
        if old is None:
            os.environ.pop("TEXINPUTS", None)
        else:
            os.environ["TEXINPUTS"] = old


def parse_by_plastex(
    paper_id: str,
    src_dir: str,
    theorem_types: Set[str],
    debugging_mode: bool
) -> List[Dict]:
    envs_to_titles = extract_envs_to_titles(src_dir, theorem_types)
    main_tex_path = os.path.abspath(get_main_tex_path(src_dir))
    main_dir = os.path.dirname(main_tex_path)

    tex = TeX()
    silent = not debugging_mode

    old_cwd = os.getcwd()
    try:
        # Critical: resolve \input/\include relative to the main file directory
        os.chdir(main_dir)

        with _with_texinputs(src_dir=os.path.abspath(src_dir), main_dir=main_dir):
            theorems: List[Dict] = []

            with _silent_plastex(silent):
                with open(main_tex_path, "r", encoding="utf-8", errors="ignore") as f:
                    tex.input(f)          # file object -> sets filename context
                    doc = tex.parse()

                for env in sorted(envs_to_titles.keys()):
                    for node in doc.getElementsByTagName(env):
                        label = _get_node_label(doc, node)
                        body = _get_node_body(node)
                        name = _get_node_name(node, envs_to_titles[env])

                        if body and name:
                            theorems.append({
                                "paper_id": paper_id,
                                "name": name,
                                "label": label,
                                "body": body,
                            })

            # pprint.pprint(theorems)
            return theorems

    except Exception:
        # If you want to debug rare misses, re-raise when debugging_mode is True
        if debugging_mode:
            raise
        return []

    finally:
        os.chdir(old_cwd)