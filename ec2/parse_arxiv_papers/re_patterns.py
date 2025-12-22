import re

SAFE_ENV_RE = re.compile(r"^[A-Za-z@][A-Za-z0-9@]*$")

TITLE_CLEAN_RE = re.compile(r"""
^\s*
(?:\\(?:noindent|ignorespaces|relax|leavevmode)\b\s*)*   # common harmless macros
(?:\{?\s*)*                                              # stray opening braces
(?:\\(?:textbf|textit|emph|rmfamily|sffamily|ttfamily
      |bfseries|itshape|scshape|upshape)\b\s*\{?\s*)*    # styling commands
""", re.VERBOSE)

NEWTHEOREM_RE = re.compile(r"""
\\newtheorem
\*?\s*
(?:<[^>]*>)?\s*
\{(?P<env>[^\}]+)\}
(?:\[[^\]]*\])?\s*          # optional [shared-counter]
\{(?P<title>[^\}]+)\}
\s*(?:\[[^\]]*\])?          # optional [within], whitespace allowed
""", re.VERBOSE)

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

DOC_CLASS_RE = re.compile(
    r"^[ \t]*[^%\n]*\\documentclass\s*(\[[\s\S]*?\])?\s*\{[^}]*\}",
    re.MULTILINE | re.DOTALL
)
INPUT_RE = re.compile(r"^[^%]*\\(input|include|subfile)\{([^}]+)\}", re.MULTILINE)

SECTION_LIKE_RE = re.compile(r"\\(section|subsection|subsubsection)\b")
THEOREM_ENV_RE = re.compile(r"\\begin\{(theorem|lemma|proposition|corollary)\}")
CITE_RE = re.compile(r"\\cite[tp]?\{")

LABEL_RE = re.compile(r"\\label\s*\{[^}]*\}")