from ..re_patterns import NEWTHEOREM_RE
from typing import Set, Tuple, Optional

def extract_env_and_title(line: str, theorem_types: Set[str]) -> Optional[Tuple[str, str]]:
    match = NEWTHEOREM_RE.match(line)

    if match:
        env = match.group("env")
        title = match.group("title").strip()
        if title.lower() in theorem_types:
            return env, title
    
    return None