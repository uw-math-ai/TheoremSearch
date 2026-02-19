import contextlib
from pathlib import Path
import os
from typing import List
from ...enums import Mode

@contextlib.contextmanager
def use_texinputs(paper_dir: Path, mode: Mode):
    """
    A context that adds to TEXINPUTS all files in `paper_dir`. Automatically cleans up TEXINPUTS
    as well.

    Parameters
    ----------
    paper_dir : Path
        The path to all of a paper's source files
    mode: Mode
        The mode to run `use_texinputs` in
    """

    old = os.environ.get("TEXINPUTS")
    sep = os.pathsep

    entries: List[str] = []
    
    abs_paper_dirpath = str(paper_dir.resolve())
    entries.append(abs_paper_dirpath)
    entries.append(abs_paper_dirpath + "//")

    prefix = sep.join(entries) + sep
    os.environ["TEXINPUTS"] = prefix + (old or "")

    if mode == Mode.DEBUGGING:
        print(f"[DEBUG] TEXINPUTS: {os.environ['TEXINPUTS']}")

    try:
        yield
    finally:
        if old is None:
            os.environ.pop("TEXINPUTS", None)
        else:
            os.environ["TEXINPUTS"] = old