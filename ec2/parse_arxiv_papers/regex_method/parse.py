from typing import Set
from ..main_tex import get_main_tex_path
import os
from .flatten import flatten_tex

def parse_by_regex(paper_id: str, src_dir: str, theorem_types: Set[str]):
    main_tex_path = get_main_tex_path(src_dir)
    main_tex_name = os.path.basename(main_tex_path)

    paper_tex = flatten_tex(main_tex_name, src_dir)

    print(paper_tex)

    return []