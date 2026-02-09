"""
Helpers for removing comments from LaTeX sources.
"""

def remove_line_comments(line: str) -> str:
    """
    Remove LaTeX comments from a single line, preserving escaped percent signs.
    
    Parameters
    ----------
    line: str
        A line of valid LaTeX

    Returns
    -------
    clean_line: str
        `line` without line comments or leading and trailing whitespace 
    """
    i = 0
    while i < len(line):
        if line[i] == "%":
            if i == 0 or line[i - 1] != "\\":
                return line[:i].strip()
        i += 1

    return line.strip()

def remove_comments(tex: str) -> str:
    """
    Removes LaTeX comments from an entire TeX source.

    Parameters
    ----------
    tex : str
        A TeX source

    Returns
    -------
    clean_tex : str
        A TeX source without comments
    """

    clean_tex = ""

    for line in tex.splitlines():
        clean_line = remove_line_comments(line) + "\n"
        clean_tex += clean_line

    return clean_tex