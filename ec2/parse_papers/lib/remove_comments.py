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