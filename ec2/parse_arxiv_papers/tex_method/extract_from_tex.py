from typing import Dict, List
from ..re_patterns import (
    NEWTHEOREM_RE,
    DECLARETHEOREM_RE,
    SPNEWTHEOREM_RE,
    NEWMDTHM_RE,
)

def _read_tex(tex_path: str) -> str:
    with open(tex_path, "rb") as tf:
        tf_raw = tf.read()

        try:
            return tf_raw.decode("utf-8")
        except UnicodeDecodeError:
            return tf_raw.decode("latin-1", errors="replace")

def extract_envs_to_titles(tex_path: str, theorem_titles: List[str]) -> Dict[str, str]:
    tex = _read_tex(tex_path)

    envs_to_titles = {}

    def add_match(m):
        env = m.group("env").strip().replace("*", "")
        title = m.group("title").strip()
        if title in theorem_titles:
            envs_to_titles[env] = title

    for m in NEWTHEOREM_RE.finditer(tex):
        add_match(m)
    for m in DECLARETHEOREM_RE.finditer(tex):
        if m.group("title"):
            add_match(m)
    for m in SPNEWTHEOREM_RE.finditer(tex):
        add_match(m)
    for m in NEWMDTHM_RE.finditer(tex):
        add_match(m)

    return envs_to_titles