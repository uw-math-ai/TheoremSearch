from typing import Set
import os
from .extract_from_tex import extract_envs_to_titles
from .main_tex import get_main_tex_path
from .thmenvcapture import inject_thmenvcapture
from .pdflatex import generate_dummy_biblatex, run_pdflatex
from .re_patterns import LABEL_RE

def parse_by_tex(paper_id: str, src_dir: str, theorem_types: Set[str]):
    envs_to_titles = {
        title: title.capitalize()
        for title in theorem_types
    }

    for src_file_name in os.listdir(src_dir):
        src_file_path = os.path.join(src_dir, src_file_name)

        if not (os.path.isfile(src_file_path) and src_file_path.endswith(".tex")):
            continue

        envs_to_titles = envs_to_titles | extract_envs_to_titles(
            src_file_path, envs_to_titles.values()
        )

    main_tex_path = get_main_tex_path(src_dir)
    main_tex_name = os.path.basename(main_tex_path)

    inject_thmenvcapture(main_tex_path, envs_to_titles, src_dir)

    generate_dummy_biblatex(src_dir)

    theorem_log_path = os.path.join(src_dir, "thm-env-capture.log")
    if os.path.exists(theorem_log_path):
        os.remove(theorem_log_path)

    run_pdflatex(main_tex_name, cwd=src_dir)

    if not os.path.exists(theorem_log_path):
        raise FileNotFoundError("thm-env-capture.log was not created")
    
    theorems = []

    with open(theorem_log_path, "r", encoding="utf-8", errors="ignore") as f:
        curr_theorem = {}

        for line in f.readlines():
            line = line.strip()

            if line == "BEGIN_ENV":
                curr_theorem = {
                    "paper_id": paper_id,
                    "label": None
                }
            elif line.startswith("name:"):
                curr_theorem["name"] = line.split("name:", 1)[1].strip()
            elif line.startswith("label:"):
                curr_theorem["label"] = line.split("label:", 1)[1].strip()
            elif line.startswith("body:"):
                curr_theorem["body"] = LABEL_RE.sub("", line.split("body:", 1)[1].strip())
            elif line == "END_ENV" and curr_theorem:
                theorems.append(curr_theorem)

    return theorems