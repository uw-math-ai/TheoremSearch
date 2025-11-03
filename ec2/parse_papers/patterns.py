import regex
from typing import Pattern, Dict

def _c(rx: str, flags=0) -> Pattern[str]:
    return regex.compile(rx, flags | regex.VERBOSE | regex.DOTALL | regex.MULTILINE)

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

NEWDEF = r"""
\\(?P<op>(?:e|g|x)?def)            # \def, \edef, \gdef, \xdef
[ \t\r\n\f]*

# --- MACRO NAME (captured separately) ---
(?P<name>
    \\[A-Za-z@]+                   # control word: \foo, \@bar
  | \\\S                           # control symbol: \!, \_, \%, etc. (one non-space char)
  | [^\s\\{}%#]                    # active char (e.g., ~), not \, space, { }, %, #
)

# allow interstitial spaces/comments after the name
(?:(?:[ \t\r\n\f]*|%[^\n]*(?:\n|$))*)    

# --- OPTIONAL PARAMS (only if a '#' exists before the next '{') ---
(?:
    (?= (?:%[^\n]*(?:\n|$)|[^{])* \# (?:%[^\n]*(?:\n|$)|[^{])* \{ )
    (?P<params> (?:%[^\n]*(?:\n|$)|[^{])*? )
)?

# spaces/comments before body
(?:(?:[ \t\r\n\f]*|%[^\n]*(?:\n|$))*)

\{                                  # --- BODY START ---
  (?P<body>
    (?:
      [^{}]+
      |
      \{ (?P>body) \}               # recursive for nested braces (regex module)
    )*
  )
\}                                  # --- BODY END ---
"""

NEWLET = r"""
    # Optional \global prefix (capture if present), then \let
    (?:\\(?P<global>global)\b)?       
    (?:(?:[ \t\r\n\f]*|%[^\n]*(?:\n|$))*)   # gaps/comments
    \\let
    (?:(?:[ \t\r\n\f]*|%[^\n]*(?:\n|$))*)   # gaps/comments

    # --- NEW (assignee) ---
    (?P<new>
        \\[A-Za-z@]+                         # control word (\foo, \@bar)
      | \\[^A-Za-z@\s]                       # control symbol (\!, \_, \%)
      | [^\s\\{}%#]                          # active char (e.g., ~), not \, space, { }, %, #
    )

    # optional '=', with spaces/comments around it
    (?:(?:[ \t\r\n\f]*|%[^\n]*(?:\n|$))*)    # gaps/comments
    =?                                       
    (?:(?:[ \t\r\n\f]*|%[^\n]*(?:\n|$))*)    

    # --- OLD (source token) ---
    (?P<old>
        \\[A-Za-z@]+
      | \\[^A-Za-z@\s]
      | [^\s\\{}%#]
    )
    """

NEWMATHOPERATOR = r"""
    \\(?P<op>DeclareMathOperator\*?)                 # \DeclareMathOperator or starred
    (?:(?:[ \t\r\n\f]*|%[^\n]*(?:\n|$))*)            # gaps/comments

    \{                                               # {cmd}
      (?P<cmd>\\[A-Za-z@]+)                          #   control word name
    \}
    (?:(?:[ \t\r\n\f]*|%[^\n]*(?:\n|$))*)            # gaps/comments

    \{                                               # {text}
      (?P<text>
        (?:                                          # balanced brace capture (regex module)
          [^{}]+
          |
          \{ (?P>text) \}
        )*
      )
    \}
    """

NEWALIASCNT = r'''\\newaliascnt\s*{\s*([A-Za-z@]+)\s*}\s*{\s*([A-Za-z@]+)\s*}'''

STATEMENTBODY_OLD = r"(?<=\\begin\{theorem\}).*?(?=\\end\{theorem\})"

STATEMENTBODY = r"""
(?s)(\\begin\{theorem\})(?:(?!\\begin\{theorem\}|\\end\{theorem\}).|(?R))*\\end\{theorem\}
"""

NEWSECTION = r"\\section\{([^}]*)\}"
NEWINPUT = r"""
\\input                # match literal \input
\s*                    # optional whitespace
\{(?P<filepath>[^{}]+)\}  # capture contents inside {...} as 'filepath'
"""
NEWUSEPACKAGE = r"""
\\usepackage                # match literal \usepackage
\s*                    # optional whitespace
\{(?P<filepath>[^{}]+)\}  # capture contents inside {...} as 'filepath'
"""

NEWCOMMAND: Pattern[str] = r"""
    \\(?P<cmd>newcommand|providecommand|DeclareRobustCommand)
    (?P<star>\*)?                       # optional star
    (?:\s|%[^\n]*\n)*                   # whitespace/comments

    # Command name, braces optional
    \{?(?P<macro_name>\\[A-Za-z@]+)\}?
    (?:\s|%[^\n]*\n)*

    # Optional [n] number of arguments
    (?:\[(?P<num_args>\d+)\])?
    (?:\s|%[^\n]*\n)*

    # Optional [default]
    (?:\[(?P<default>[^\[\]\{\}]*)\])?
    (?:\s|%[^\n]*\n)*

    # Definition body with balanced/nested braces
    \{
        (?P<body>
            (?:
                [^{}]
              | \{(?P>body)\}
            )*
        )
    \}
"""


NEWCOMMANDOLD: Pattern[str] = r"""
    \\(?P<cmd>newcommand|providecommand|DeclareRobustCommand)
    (?P<star>\*)?                       # \newcommand or \newcommand*
    (?:\s|%[^\n]*\n)*                               # whitespace/comments

    # Command name: either {\foo} or \foo
    (?:
        \{(?P<name_braced>\\[A-Za-z@]+)\}           # {\foo}
      | (?P<name_unbraced>\\[A-Za-z@]+)             # \foo
    )
    (?:\s|%[^\n]*\n)*

    # Optional [n] number of arguments
    (?:\[(?P<num_args>\d+)\])?
    (?:\s|%[^\n]*\n)*

    # Optional [default] (only meaningful if num_args >= 1; we don't enforce here)
    (?:\[(?P<default>[^\[\]\{\}]*)\])?
    (?:\s|%[^\n]*\n)*

    # Definition body with balanced/nested braces
    \{
        (?P<body>
            (?:
                [^{}]                               # any non-brace
              | \{(?P>body)\}                       # recursively match nested {...}
            )*
        )
    \}
    """


NEWLABEL = regex.compile(r"""
\\label                             # match literal \label
\s*                                 # optional whitespace
\{(?P<label>[^{}]+)\}               # capture everything inside {...} as 'label'
""", regex.VERBOSE | regex.DOTALL | regex.MULTILINE)

def SPECIFICTHEOREM(name: str) -> Pattern[str]:
    name = regex.escape(name) # distinguishes between "theorem" and "theorem*"
    return rf"(?<=\\begin\{{{name}\}}).*?(?=\\end\{{{name}\}})"

def SPECIFICTHEOREM_HEAD(name: str) -> Pattern[str]:
    return rf"(?<=\\begin\{{{name}\}}).*?(?=\\end\{{{name}\}})"

__all__ = ["NEWTHEOREM", "NEWCOMMAND", "NEWENVIRONMENT",
           "NEWALIASCNT", "SPECIFICTHEOREM", "NEWSECTION", 
           "STATEMENTBODY", "NEWINPUT", "NEWUSEPACKAGE",
           "NEWDEF", "NEWLET", "NEWMATHOPERATOR",
           "NEWLABEL"]