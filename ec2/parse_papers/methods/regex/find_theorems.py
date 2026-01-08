from typing import Dict, List
import re
from ...types import Theorem
from ...lib.separate_body_and_label import separate_body_and_label

BEGIN_RE = re.compile(r"\\begin\s*\{(?P<env>[^}]+)\}")
NOTE_RE = re.compile(r"^\[(?P<note>[^\]]*)\]")
PROCLAIM_RE = re.compile(r"\\proclaim\s*\{(?P<name>[^}]+)\}")
ENDPROCLAIM_RE = re.compile(r"\\endproclaim")


def _parse_env_content(env_content: str, type: str) -> Theorem:
    env_content = env_content.strip()

    note = None
    note_match = NOTE_RE.match(env_content)
    if note_match:
        note = note_match.group("note")
        env_content = NOTE_RE.sub("", env_content, count=1).lstrip()

    body, label = separate_body_and_label(env_content)

    return {
        "type": type,
        "ref": None,
        "note": note,
        "label": label,
        "body": body,
    }


def find_theorems(tex: str, theorem_envs: Dict[str, str]) -> List[Theorem]:
    theorems: List[Theorem] = []
    allowed_types = set(theorem_envs.values())
    pos = 0

    while True:
        proclaim_match = PROCLAIM_RE.search(tex, pos)
        if not proclaim_match:
            break

        start_proclaim = proclaim_match.end()

        name = proclaim_match.group("name").lstrip(r"\bf").strip()
        name_segments = name.split()

        type_ = name_segments[0].lower() if len(name_segments) >= 1 else None
        if type_ not in allowed_types:
            pos = start_proclaim
            continue

        ref = name_segments[1] if len(name_segments) >= 2 else None
        note = (
            name_segments[2].lstrip("(").rstrip(")")
            if len(name_segments) >= 3
            and name_segments[2].startswith("(")
            and name_segments[2].endswith(")")
            else None
        )

        end_proclaim_match = ENDPROCLAIM_RE.search(tex, start_proclaim)
        if not end_proclaim_match:
            pos = start_proclaim
            continue

        body_and_label = tex[start_proclaim:end_proclaim_match.start()]
        body, label = separate_body_and_label(body_and_label)

        theorems.append(
            {
                "type": type_,
                "ref": ref,
                "note": note,
                "body": body,
                "label": label,
            }
        )

        pos = end_proclaim_match.end()

    pos = 0

    while True:
        begin_match = BEGIN_RE.search(tex, pos)
        if not begin_match:
            break

        env = begin_match.group("env")
        start_body = begin_match.end()

        if env not in theorem_envs:
            pos = start_body
            continue

        end_re = re.compile(r"\\end\{" + re.escape(env) + r"\}")
        end_match = end_re.search(tex, start_body)

        if not end_match:
            pos = start_body
            continue

        env_content = tex[start_body:end_match.start()]
        theorems.append(_parse_env_content(env_content, theorem_envs[env]))

        pos = end_match.end()

    return theorems