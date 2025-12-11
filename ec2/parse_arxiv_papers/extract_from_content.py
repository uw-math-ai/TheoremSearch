from .re_patterns import (
    NEWTHEOREM_RE,
    DECLARETHEOREM_RE,
    SPNEWTHEOREM_RE,
    NEWMDTHM_RE,
)
THEOREM_TITLES = {"Theorem", "Lemma", "Proposition", "Corollary"}

def extract_theorem_envs(tex: str):
    envs_to_titles = {}

    def add_match(m):
        env = m.group("env").strip().replace("*", "")
        title = m.group("title").strip()
        if title in THEOREM_TITLES:
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
