import re

NEWTHEOREM_RE = re.compile(
    r"""
    \\newtheorem          # \newtheorem
    \*?                   # optional star
    \s*
    (?:<[^>]*>)?          # optional beamer overlay: <...>
    \s*
    \{(?P<env>[^\}]+)\}   # {environment-name}
    (?:\[[^\]]*\])?       # optional [like-this]
    \s*
    \{(?P<title>[^\}]+)\} # {Theorem}
    """,
    re.VERBOSE
)

DECLARETHEOREM_RE = re.compile(
    r"""
    \\declaretheorem
    \s*
    (?:\[
        (?:
          (?:[^\]]*?,)?         # junk before
          \s*name=(?P<title>[^,\]]+)
          [^\]]*
        )
    \])?
    \s*
    \{(?P<env>[^\}]+)\}
    """,
    re.VERBOSE
)


SPNEWTHEOREM_RE = re.compile(
    r"""
    \\spnewtheorem
    \s*
    \{(?P<env>[^\}]+)\}     # {thm}
    \s*
    (?:\[[^\]]*\])?         # optional [thm]
    \s*
    \{(?P<title>[^\}]+)\}   # {Theorem}
    """,
    re.VERBOSE
)

NEWMDTHM_RE = re.compile(
    r"""
    \\newmdtheoremenv
    \s*
    (?:\[[^\]]*\])?         # optional [options]
    \s*
    \{(?P<env>[^\}]+)\}     # {env}
    \s*
    \{(?P<title>[^\}]+)\}   # {Theorem}
    """,
    re.VERBOSE
)

DOC_CLASS_RE = re.compile(r"^[^%]*\\documentclass(\[.*?\])?\{.*?\}", re.MULTILINE)
INPUT_RE = re.compile(r"^[^%]*\\(input|include|subfile)\{([^}]+)\}", re.MULTILINE)

SECTION_LIKE_RE = re.compile(r"\\(section|subsection|subsubsection)\b")
THEOREM_ENV_RE = re.compile(r"\\begin\{(theorem|lemma|proposition|corollary|remark)\}")
CITE_RE = re.compile(r"\\cite[tp]?\{")

LABEL_RE = re.compile(r"\\label\s*\{[^}]*\}")