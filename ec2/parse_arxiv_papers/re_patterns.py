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