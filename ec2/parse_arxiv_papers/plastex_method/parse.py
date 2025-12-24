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
import signal

def _flag_for_truncation(body) -> bool:
    if len(body) >= 32:
        return False
    return ("." not in body) and ("$" not in body) and ("\\" not in body)

def _get_node_body(node) -> str:
    parts = []
    for child in getattr(node, "childNodes", []) or []:
        src = getattr(child, "source", None)
        if isinstance(src, str) and src.strip():
            parts.append(src.strip())
        else:
            parts.append(child.textContent)
    
    body = LABEL_RE.sub("", "".join(parts).strip()).strip()

    if _flag_for_truncation(body):
        return ""
    else:
        return body

def _build_target_to_label(doc) -> dict[int, str]:
    out = {}
    labels = getattr(doc.context, "labels", {}) or {}
    for lab, target in labels.items():
        if isinstance(lab, str) and "plasTeX" not in lab and target is not None:
            out[id(target)] = lab
    return out

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

class _ParseTimeout(Exception):
    pass

def _alarm_handler(signum, frame):
    raise _ParseTimeout("plasTeX parse timed out")

@contextlib.contextmanager
def _with_timeout(seconds: int):
    # No-op if seconds is falsy or non-positive
    if not seconds or seconds <= 0:
        yield
        return

    old_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(int(seconds))
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)

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
    old = os.environ.get("TEXINPUTS")
    sep = os.pathsep

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
    timeout: int,
    debugging_mode: bool
) -> List[Dict]:
    envs_to_titles = extract_envs_to_titles(src_dir, theorem_types)
    main_tex_path = os.path.abspath(get_main_tex_path(src_dir))
    main_dir = os.path.dirname(main_tex_path)

    tex = TeX()
    silent = not debugging_mode

    old_cwd = os.getcwd()
    try:
        os.chdir(main_dir)

        with _with_texinputs(src_dir=os.path.abspath(src_dir), main_dir=main_dir):
            theorems: List[Dict] = []

            with _silent_plastex(silent):
                # Enforce a hard timeout INSIDE the worker process.
                with _with_timeout(timeout):
                    with open(main_tex_path, "r", encoding="utf-8", errors="ignore") as f:
                        tex.input(f)
                        doc = tex.parse()

                    target_to_label = _build_target_to_label(doc)

                    for env in sorted(envs_to_titles.keys()):
                        for node in doc.getElementsByTagName(env):
                            body = _get_node_body(node)
                            if not body:
                                return []

                            label = target_to_label.get(id(node))
                            name = _get_node_name(node, envs_to_titles[env])

                            if body and name:
                                theorems.append({
                                    "paper_id": paper_id,
                                    "name": name,
                                    "label": label,
                                    "body": body,
                                })

            return theorems

    except _ParseTimeout:
        # Hard timeout triggered inside worker
        if debugging_mode:
            raise
        return []

    except Exception:
        if debugging_mode:
            raise
        return []

    finally:
        os.chdir(old_cwd)