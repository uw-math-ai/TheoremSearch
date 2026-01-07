from pathlib import Path
import subprocess
from ...enums import Mode

def flatten_paper(main_file: Path, paper_dir: Path, mode: Mode) -> str:
    """
    Flattens a paper's source files into a single string.

    Parameters
    ----------
    main_file : Path
        Path to main file
    paper_dir : Path
        Path to a paper's source files
    mode : Mode
        Mode to run `flatten_paper` in

    Returns
    -------
    tex : Flat LaTeX of the paper
    """

    cmd = [
        "latex-flatten",
        str(main_file),
        "-q",
        "--hide-figures"
    ]

    if mode == Mode.DEBUGGING:
        cmd.extend(["-d", str(paper_dir / "DEBUG_flat")])

    subprocess.run(
        cmd,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    if mode == Mode.DEBUGGING:
        return (paper_dir / "DEBUG_flat" / main_file.name).read_text()
    else:
        return main_file.read_text()