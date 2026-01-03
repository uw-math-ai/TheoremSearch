from pathlib import Path
from .expand_latex_macros import expand_latex_macros
from ...enums import Mode

MACRO_FILE_EXTENSIONS = { "*.tex", "*.ltx", "*.sty", "*.cls", "*.clo", "*.def", "*.cfg" }

def expand_macros(tex: str, paper_dir: Path, mode: Mode) -> str:
    """
    Expands basic macros with macro sources found in `paper_dir`.

    Parameters
    ----------
    tex : str
        TeX with macros to expand
    paper_dir : Path
        Path to a paper's source files
    mode : Mode
        Mode to run `expand_macros` in

    Returns
    -------
    expanded_tex : str
        TeX with macros expanded
    """

    macro_sources = []

    for ext in MACRO_FILE_EXTENSIONS:
        for macro_file in paper_dir.rglob(ext):
            with open(macro_file, "r", errors="ignore") as mf:
                macro_sources.append(mf.read())

    try:
        return expand_latex_macros(tex, extra_macro_sources=macro_sources)
    except Exception as e:
        if mode == Mode.DEBUGGING:
            print(f"[DEBUG] Macro expansion failed: {e}")

        return tex