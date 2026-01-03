from pathlib import Path
from typing import List
import subprocess
import textwrap
from ...enums import Mode

def _generate_dummy_package(package: str, paper_dir: Path):
    sty_path = paper_dir / (package + ".sty")
    
    if sty_path.exists():
        return
    
    dummy = textwrap.dedent(rf"""
    %% {package}.sty -- dummy stub generated for theorem capture
    \NeedsTeXFormat{{LaTeX2e}}
    \ProvidesPackage{{{package}}}[Dummy stub]
    \endinput
    """).lstrip("\n")

    with open(sty_path, "w", encoding="utf-8") as f:
        f.write(dummy)

def run_pdflatex(
    main_file: Path,
    paper_dir: Path,
    mode: Mode,
    _missing_packages: List[str] = []
) -> Path:
    """
    Runs pdflatex on a paper's source files to generate `thm-env-capture.log`.

    Parameters
    ----------
    main_file : Path
        Path to main file
    paper_dir : Path
        Path to paper's source files
    mode : Mode
        The mode to run `run_pdflatex` in

    Returns
    -------
    theorem_log_path : Path
        Path to theorem log file
    """

    if mode == Mode.DEBUGGING and _missing_packages:
        print("[DEBUG] Missing packages:", _missing_packages)

    for package in _missing_packages:
        _generate_dummy_package(package, paper_dir)

    _missing_packages = []

    cmd = [
        "pdflatex", 
        "-draftmode", 
        "-interaction=nonstopmode", 
        "-recorder", 
        str(main_file.relative_to(paper_dir))
    ]
    proc = subprocess.run(
        cmd,
        cwd=paper_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace"
    )
    stderr = proc.stdout

    if mode == Mode.DEBUGGING:
        debug_stderr_file = paper_dir / "DEBUG_stderr.log"

        with open(debug_stderr_file, "w") as dsf:
            dsf.write(stderr)    

    for line in stderr.splitlines():
        if "File `" in line and ".sty' not found" in line:
            package = line.split("File `", 1)[1].split(".sty", 1)[0]

            if package != "thmenvcapture":
                _missing_packages.append(package)

    if _missing_packages:
        return run_pdflatex(
            main_file,
            paper_dir,
            mode,
            _missing_packages
        )
    
    theorem_log_path = paper_dir / "thm-env-capture.log"

    if not theorem_log_path.exists():
        raise FileNotFoundError("them-env-capture.log was not created")

    return theorem_log_path