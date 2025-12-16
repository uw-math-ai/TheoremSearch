from typing import Set
import os
from .extract_from_tex import extract_envs_to_titles
from ..main_tex import get_main_tex_path
from .thmenvcapture import inject_thmenvcapture
from .pdflatex import generate_dummy_biblatex, run_pdflatex
from ..re_patterns import LABEL_RE

def parse_by_tex(
    paper_id: str,
    src_dir: str,
    theorem_types: Set[str],
    timeout: int
):
    envs_to_titles = extract_envs_to_titles(src_dir, theorem_types)

    main_tex_path = get_main_tex_path(src_dir)
    main_tex_name = os.path.basename(main_tex_path)

    inject_thmenvcapture(main_tex_path, envs_to_titles, src_dir)
    generate_dummy_biblatex(src_dir)

    theorem_log_path = os.path.join(src_dir, "thm-env-capture.log")
    if os.path.exists(theorem_log_path):
        os.remove(theorem_log_path)

    run_pdflatex(main_tex_name, cwd=src_dir, timeout=timeout)

    if not os.path.exists(theorem_log_path):
        raise FileNotFoundError("thm-env-capture.log was not created")

    theorems = []

    with open(theorem_log_path, "r", encoding="utf-8", errors="ignore") as f:
        curr = None
        keep = False

        for raw in f:
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
                head = curr["name"].split(" ", 1)[0].lower()
                if head not in theorem_types:
                    keep = False

            elif line.startswith("label:"):
                curr["label"] = line.split("label:", 1)[1].strip()

            elif line.startswith("body:"):
                body = line.split("body:", 1)[1].strip()
                body = LABEL_RE.sub("", body).replace("\\protect", "")
                curr["body"] = body
                if not body:
                    keep = False

    return theorems
