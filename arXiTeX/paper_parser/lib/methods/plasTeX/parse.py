from pathlib import Path
from plasTeX.TeX import TeX
from typing import List
from operator import attrgetter
from .use_texinputs import use_texinputs
from .parse_node import parse_node
from .use_plastex_log_capturer import use_plastex_log_capturer
from ....types import Theorem
from ...utils.guess_main_file import guess_main_file
from ...utils.extract_theorem_envs import extract_theorem_envs

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

    # if mode == Mode.DEBUGGING:
    #     with open(paper_dir / "DEBUG_doc.xml", "w") as debug_doc_xml:
    #         debug_doc_xml.write(doc.toXML())

    for env, type_ in theorem_envs.items():
        for theorem_node in doc.getElementsByTagName(env):
            ref, note, label, body = parse_node(theorem_node)

            proof = None
            proof_node_parent = theorem_node.parentNode.nextSibling
            if proof_node_parent:
                for proof_node in proof_node_parent.getElementsByTagName("proof"):
                    _, _, _, proof = parse_node(proof_node)

                    break

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