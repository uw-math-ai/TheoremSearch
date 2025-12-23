from typing import Set
import os
from .extract_from_tex import extract_envs_to_titles
from ..main_tex import get_main_tex_path
from .thmenvcapture import inject_thmenvcapture
from .pdflatex import generate_dummy_biblatex, run_pdflatex
from ..re_patterns import LABEL_RE
import pyperclip
from expand_latex_macros import expand_latex_macros

def parse_by_tex(
    paper_id: str,
    src_dir: str,
    theorem_types: Set[str],
    timeout: int,
    debugging_mode: bool
):
    envs_to_titles = extract_envs_to_titles(src_dir, theorem_types)

    if debugging_mode:
        print("envs_to_titles:", envs_to_titles)

    main_tex_path = get_main_tex_path(src_dir)
    main_tex_name = os.path.basename(main_tex_path)

    if debugging_mode:
        print("main_tex_path:", main_tex_path)

    thmenvcapture_content = inject_thmenvcapture(main_tex_path, envs_to_titles, src_dir)

    if debugging_mode:
        try:
            pyperclip.copy(thmenvcapture_content)
            print("thmenvcapture.sty: copied to clipboard")
        except Exception:
            print("thmenvcapture.sty: not copied to clipboard (no xclip, xselect, etc.)")

    generate_dummy_biblatex(src_dir)

    theorem_log_path = os.path.join(src_dir, "thm-env-capture.log")
    if os.path.exists(theorem_log_path):
        os.remove(theorem_log_path)

    run_pdflatex(main_tex_name, cwd=src_dir, timeout=timeout, debugging_mode=debugging_mode)

    if not os.path.exists(theorem_log_path):
        raise FileNotFoundError("thm-env-capture.log was not created")
    
    macro_sources = []
    for root, _, files in os.walk(src_dir):
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            # include typical LaTeX text sources
            if ext in (".tex", ".ltx", ".sty", ".cls", ".clo", ".def", ".cfg"):
                macro_sources.append(os.path.join(root, fn))

    with open(theorem_log_path, "r", encoding="utf-8", errors="ignore") as f:
        log_str = f.read()

    try:
        log_str = expand_latex_macros(log_str, extra_macro_sources=macro_sources)
    except Exception as e:
        # Minimal behavior: if expansion fails, fall back to raw log
        if debugging_mode:
            print("expand_latex_macros failed; using raw log. Error:", repr(e))

    theorems = []

    curr = None
    keep = False

    for raw in log_str.splitlines():
        line = raw.strip()

        if line == "BEGIN_ENV":
            curr = {"paper_id": paper_id, "label": None, "name": "", "body": ""}
            keep = True
            continue

        if line == "END_ENV":
            if keep and curr and curr["name"] and curr["body"]:
                theorems.append(curr)
            curr = None
            keep = False
            continue

        if not keep or curr is None:
            continue

        if line.startswith("name:"):
            curr["name"] = line.split("name:", 1)[1].strip()

        elif line.startswith("label:"):
            label = line.split("label:", 1)[1].strip()
            if label:
                curr["label"] = label

        elif line.startswith("body:"):
            body = line.split("body:", 1)[1].strip()
            body = LABEL_RE.sub("", body).replace("\\protect", "")
            curr["body"] = body
            if not body:
                keep = False

    return theorems