import regex
from typing import Pattern, Dict

def _c(rx: str, flags=0) -> Pattern[str]:
    return regex.compile(rx, flags | regex.VERBOSE | regex.DOTALL | regex.MULTILINE)

# captures macro commands
NEWCOMMAND: Pattern[str] = r"""
\\newcommand\*?
\s*\{(?P<name>\\[A-Za-z@]+)\}
\s*(?:\[\d+\])?
\s*(?:\[[^\]]*\])?
\s*\{
  (?P<body>
    (?:
      [^{}]
      |
      \{(?P>body)\}
    )*
  )
\}
"""

# captures theorem commands
NEWTHEOREM: Pattern[str] = r"""
\\newtheorem(?P<star>\*)?           # optional * captured as 'star'
\s*\{(?P<env>[^{}]+)\}              # {env}
\s*(?:\[(?P<shared>[^\]]*)\]\s*)?   # [shared] (optional)
\{                                   # {title} with nested braces
  (?P<title>
    (?:
      [^{}]
      |
      \{(?P>title)\}
    )*
  )
\}
\s*(?:\[(?P<within>[^\]]*)\])?      # [within] (optional)
(?=\s*(?:\\|%|\Z))                   # next token/comment/end
"""

# captures environment macros
NEWENVIRONMENT: Pattern[str] = r"""
\\newenvironment\*?                  # \newenvironment or \newenvironment*
\s*\{(?P<name>[A-Za-z@]+)\}          # {name} (no backslash)
\s*(?:\[(?P<num>\d+)\])?             # optional [num]
\s*(?:\[(?P<default>[^\]]*)\])?      # optional [default] (only valid if num>=1)
\s*\{(?P<begin>                      # {begin-code} with nested braces
    (?:
      [^{}]                          # any non-brace
      | \{(?P>begin)\}               # or recursively nested {begin}
    )*
)\}
\s*\{(?P<end>                        # {end-code} with nested braces
    (?:
      [^{}]
      | \{(?P>end)\}
    )*
)\}
"""

NEWALIASCNT = r'''\\newaliascnt\s*{\s*([A-Za-z@]+)\s*}\s*{\s*([A-Za-z@]+)\s*}'''
STATEMENTBODY = r"(?<=\\begin\{theorem\}).*?(?=\\end\{theorem\})"
NEWSECTION = r"\\section\{([^}]*)\}"

def SPECIFICTHEOREM(name: str) -> Pattern[str]:
    name = regex.escape(name) # distinguishes between "theorem" and "theorem*"
    return rf"(?<=\\begin\{{{name}\}}).*?(?=\\end\{{{name}\}})"

def SPECIFICTHEOREM_HEAD(name: str) -> Pattern[str]:
    return rf"(?<=\\begin\{{{name}\}}).*?(?=\\end\{{{name}\}})"

__all__ = ["NEWTHEOREM", "NEWCOMMAND", "NEWENVIRONMENT", "NEWALIASCNT", "SPECIFICTHEOREM", "NEWSECTION", "STATEMENTBODY"]