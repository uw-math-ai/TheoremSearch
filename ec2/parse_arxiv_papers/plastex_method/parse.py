from typing import Set, Dict, List, Optional
import os
import io
import contextlib
import logging
import subprocess

from ..re_patterns import LABEL_RE
from ..main_tex import get_main_tex_path
from ..tex_method.extract_from_tex import extract_envs_to_titles

from plasTeX.TeX import TeX
from plasTeX.Logging import disableLogging


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


def _flatten_main_tex(main_tex_path: str) -> None:
    cmd = ["latex-flatten", main_tex_path, "--inplace"]
    result = subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        # re-run once capturing output so you actually get diagnostics
        result2 = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        raise RuntimeError(
            "latex-flatten failed\n"
            f"STDOUT:\n{result2.stdout}\n"
            f"STDERR:\n{result2.stderr}"
        )


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

    main_tex_path = get_main_tex_path(src_dir)

    _flatten_main_tex(main_tex_path)

    tex = TeX()

    silent = not debugging_mode

    try:
        theorems: List[Dict] = []

        with _silent_plastex(silent):
            tex.input(open(main_tex_path, "r", encoding="utf-8", errors="ignore").read())
            doc = tex.parse()

            for env in sorted(envs_to_titles.keys()):
                if not env or any(ch.isspace() for ch in env):
                    continue

                for node in doc.getElementsByTagName(env):
                    label = _get_node_label(doc, node)
                    number = node.ref.source if getattr(node, "ref", None) else None

                    body = body_inner_latex(node)
                    body = LABEL_RE.sub("", body).strip()

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

                    theorems.append({
                        "paper_id": paper_id,
                        "name": name,
                        "label": label,
                        "body": body,
                    })

        return theorems

    except Exception:
        return []