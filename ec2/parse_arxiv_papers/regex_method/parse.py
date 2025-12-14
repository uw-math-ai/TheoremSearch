from typing import Set, List, Dict
from ..main_tex import get_main_tex_path
import os
from .flatten import flatten_tex
from .TexLineStream import TexLineStream
from .comments import strip_comments
from .verbatim import is_verbatim_end, extract_verbatim_start
from .envs import extract_env_and_title

def parse_by_regex(paper_id: str, src_dir: str, theorem_types: Set[str]) -> List[Dict]:
    main_tex_path = get_main_tex_path(src_dir)
    main_tex_name = os.path.basename(main_tex_path)

    theorems = []

    paper_tex = flatten_tex(main_tex_name, src_dir)
    paper_tex_stream = TexLineStream(paper_tex)

    macros = {}
    aliases = {}
    env_to_title = {}
    active_env_stack = []
    curr_section_path = ""
    verbatim_stack = []
    
    for line_num, line in paper_tex_stream:
        # STRIP COMMENTS
        line = strip_comments(line)

        if not line.strip():
            continue

        # IGNORE VERBATIM ENVS
        if verbatim_stack:
            if is_verbatim_end(line, verbatim_stack[-1]):
                verbatim_stack.pop()

            continue
        else:
            verbatim_start = extract_verbatim_start(line)

            if verbatim_start:
                verbatim_stack.append(verbatim_start)

                continue

        # EXTRACT THEOREM ENV DEFS
        env_and_title = extract_env_and_title(line, theorem_types)
        
        if env_and_title:
            env_to_title[env_and_title[0]] = env_and_title[1]

        # EXTRACT MACROS (MACROS, DEFS, ALIASES)

        # HANDLE THEOREM ENVS



    return theorems