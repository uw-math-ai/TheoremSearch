from typing import Dict, Set
from ..re_patterns import (
    NEWTHEOREM_RE,
    DECLARETHEOREM_RE,
    SPNEWTHEOREM_RE,
    NEWMDTHM_RE,
    SAFE_ENV_RE
)
import os

def _read_tex(tex_path: str) -> str:
    with open(tex_path, "rb") as tf:
        tf_raw = tf.read()

        try:
            return tf_raw.decode("utf-8")
        except UnicodeDecodeError:
            return tf_raw.decode("latin-1", errors="replace")

def _extract_envs_to_titles_from_tex(tex_path: str, theorem_types: Set[str]) -> Dict[str, str]:
    tex = _read_tex(tex_path)

    envs_to_titles = {}

    def add_match(m):
        env = m.group("env").strip().replace("*", "")

        if not SAFE_ENV_RE.match(env):
            return

        title = m.group("title").strip().lower()

        for tt in theorem_types:
            if tt in title:
                envs_to_titles[env] = tt.capitalize()
                break

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

def extract_envs_to_titles(src_dir: str, theorem_types: Set[str]):
    envs_to_titles = {
        title: title.capitalize()
        for title in theorem_types
    }

    for src_file_name in os.listdir(src_dir):
        src_file_path = os.path.join(src_dir, src_file_name)

        if not os.path.isfile(src_file_path):
            continue

        envs_to_titles = envs_to_titles | _extract_envs_to_titles_from_tex(
            src_file_path, theorem_types
        )

    return envs_to_titles