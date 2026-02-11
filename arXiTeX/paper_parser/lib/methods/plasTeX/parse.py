import re
from pathlib import Path
from plasTeX.TeX import TeX
from typing import List, Dict, Optional
from operator import attrgetter
from .use_texinputs import use_texinputs
from .parse_node import parse_node
from .use_plastex_log_capturer import use_plastex_log_capturer
from ....types import Theorem
from ...utils.guess_main_file import guess_main_file
from ...utils.extract_theorem_envs import extract_theorem_envs

_PROOF_NOTE_LABEL_RE = re.compile(
    r"\b(?:proof|proving)\b[^\n\\]*?\\(?:c|auto)?ref\s*\{\s*([^}]+?)\s*\}",
    re.IGNORECASE
)

_PROOF_LOOKAHEAD = 3

def parse_by_plastex(
    paper_dir: Path
) -> List[Theorem]:
    """
    Parses a paper's source files into a list of theorems using plasTeX.

    Parameters
    ----------
    paper_dir : Path
        The path to all of a paper's source files

    Returns
    -------
    theorems: List[Theorem]
        A list of plasTeX-parsed theorems
    """

    main_file = guess_main_file(paper_dir)
    theorem_envs = extract_theorem_envs(paper_dir)

    theorems: List[Theorem] = []
    tex = TeX()

    with use_texinputs(paper_dir), use_plastex_log_capturer():
        with open(main_file, "r", errors="ignore") as f:
            tex.input(f)
            doc = tex.parse()

    proof_by_label: Dict[str, str] = {}

    for proof_node in list(doc.getElementsByTagName("proof")):
        _, proof_note, _, proof_candidate = parse_node(proof_node)

        if proof_note:
            m = _PROOF_NOTE_LABEL_RE.search(proof_note)
            if m:
                ref_label = m.group(1).strip()
                proof_by_label.setdefault(ref_label, proof_candidate)

                proof_node.parentNode.removeChild(proof_node)

    for env, type_ in theorem_envs.items():
        for theorem_node in doc.getElementsByTagName(env):
            ref, note, label, body = parse_node(theorem_node)

            proof: Optional[str] = None

            if label and label in proof_by_label:
                proof = proof_by_label.pop(label)

            if proof is None:
                proof_lookahead_left = _PROOF_LOOKAHEAD
                current_node = theorem_node.parentNode.nextSibling

                while proof is None and proof_lookahead_left > 0 and current_node:
                    node_name = getattr(current_node, "nodeName", "")

                    if node_name in theorem_envs:
                        break

                    for proof_node in current_node.getElementsByTagName("proof"):
                        _, _, _, proof = parse_node(proof_node)
                        current_node.removeChild(proof_node)
                        break

                    proof_lookahead_left -= 1
                    current_node = current_node.nextSibling

            theorems.append(Theorem(
                type=type_,
                ref=ref,
                note=note,
                label=label,
                body=body,
                proof=proof or None
            ))

    theorems.sort(key=attrgetter("ref"))

    return theorems