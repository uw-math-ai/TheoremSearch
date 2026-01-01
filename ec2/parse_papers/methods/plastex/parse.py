from pathlib import Path
from ....parse_papers.enums import Mode
from ...types import Theorem
from typing import List
from ...lib.guess_main_file import guess_main_file
from ...lib.extract_theorem_envs import extract_theorem_envs
from .use_texinputs import use_texinputs
from plasTeX.TeX import TeX
from .parse_node import parse_node
from .use_captured_plastex_logs import use_captured_plastex_logs

def parse_by_plastex(
    paper_dir: Path,
    theorem_types: List[str],
    mode: Mode = Mode.PRODUCTION
) -> List[Theorem]:
    """
    Parses a paper's source files into a list of theorems using plasTeX.

    Parameters
    ----------
    paper_dir : Path
        The path to all of a paper's source files
    theorems_types : List[str]
        Possible theorem types
    mode : Mode
        The mode to run `parse_by_plastex` in

    Returns
    -------
    theorems: List[Theorem]
        A list of plasTeX-parsed theorems
    """

    main_file = guess_main_file(paper_dir, mode=mode)
    theorem_envs = extract_theorem_envs(paper_dir, theorem_types, mode=mode)

    theorems: List[Theorem] = []
    tex = TeX()
    
    with use_texinputs(paper_dir, mode=mode), use_captured_plastex_logs(paper_dir, mode=mode):
        with open(main_file, "r", errors="ignore") as f:
            tex.input(f)
            doc = tex.parse()

    if mode == Mode.DEBUGGING:
        with open(paper_dir / "DEBUG_doc.xml", "w") as debug_doc_xml:
            debug_doc_xml.write(doc.toXML())

    for env, type_ in theorem_envs.items():
        for node in doc.getElementsByTagName(env):
            ref, note, label, body = parse_node(node)

            theorems.append({
                "type": type_,
                "ref": ref,
                "note": note,
                "label": label,
                "body": body
            })

    if mode == Mode.DEBUGGING:
        import json

        with open(paper_dir / "DEBUG_theorems.json", "w") as debug_theorems_json:
            json.dump(theorems, debug_theorems_json, indent=4)

    return theorems