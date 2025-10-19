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

NEWPROVIDECOMMAND = r"""
    \\(?P<op>providecommand\*?)                    # \providecommand or \providecommand*
    (?:(?:[ \t\r\n\f]*|%[^\n]*(?:\n|$))*)          # gaps/comments

    \{                                             # { \cmd }
      (?P<cmd>\\[A-Za-z@]+)                        #   control word name
    \}
    (?:(?:[ \t\r\n\f]*|%[^\n]*(?:\n|$))*)          # gaps/comments

    # Optional [nargs]
    (?:\[
        (?P<nargs>[1-9])                           #   number of arguments (1..9)
      \]
      (?:(?:[ \t\r\n\f]*|%[^\n]*(?:\n|$))*)        #   gaps/comments
    )?

    # Optional [default] (only meaningful if nargs >= 1, but we don't enforce here)
    (?:\[
        (?P<default>
          (?:
            [^\[\]]+                               #   anything but [ or ]
            | \{ (?:(?:[^{}]+)|\{(?0)\})* \}       #   allow balanced {...} inside default
          )*?
        )
      \]
      (?:(?:[ \t\r\n\f]*|%[^\n]*(?:\n|$))*)        #   gaps/comments
    )?

    \{                                             # { body }
      (?P<body>
        (?:
          [^{}]+
          | \{ (?P>body) \}                        # recursive for balanced braces
        )*
      )
    \}
    """

NEWROBUSTCOMMAND = r"""
    \\(?P<op>DeclareRobustCommand\*?)                    # \providecommand or \providecommand*
    (?:(?:[ \t\r\n\f]*|%[^\n]*(?:\n|$))*)          # gaps/comments

    \{                                             # { \cmd }
      (?P<cmd>\\[A-Za-z@]+)                        #   control word name
    \}
    (?:(?:[ \t\r\n\f]*|%[^\n]*(?:\n|$))*)          # gaps/comments

    # Optional [nargs]
    (?:\[
        (?P<nargs>[1-9])                           #   number of arguments (1..9)
      \]
      (?:(?:[ \t\r\n\f]*|%[^\n]*(?:\n|$))*)        #   gaps/comments
    )?

    # Optional [default] (only meaningful if nargs >= 1, but we don't enforce here)
    (?:\[
        (?P<default>
          (?:
            [^\[\]]+                               #   anything but [ or ]
            | \{ (?:(?:[^{}]+)|\{(?0)\})* \}       #   allow balanced {...} inside default
          )*?
        )
      \]
      (?:(?:[ \t\r\n\f]*|%[^\n]*(?:\n|$))*)        #   gaps/comments
    )?

    \{                                             # { body }
      (?P<body>
        (?:
          [^{}]+
          | \{ (?P>body) \}                        # recursive for balanced braces
        )*
      )
    \}
    """

NEWALIASCNT = r'''\\newaliascnt\s*{\s*([A-Za-z@]+)\s*}\s*{\s*([A-Za-z@]+)\s*}'''
STATEMENTBODY = r"(?<=\\begin\{theorem\}).*?(?=\\end\{theorem\})"
NEWSECTION = r"\\section\{([^}]*)\}"
NEWINPUT = r""
NEWINCLUDE = r""

def SPECIFICTHEOREM(name: str) -> Pattern[str]:
    name = regex.escape(name) # distinguishes between "theorem" and "theorem*"
    return rf"(?<=\\begin\{{{name}\}}).*?(?=\\end\{{{name}\}})"

def SPECIFICTHEOREM_HEAD(name: str) -> Pattern[str]:
    return rf"(?<=\\begin\{{{name}\}}).*?(?=\\end\{{{name}\}})"

__all__ = ["NEWTHEOREM", "NEWCOMMAND", "NEWENVIRONMENT",
           "NEWALIASCNT", "SPECIFICTHEOREM", "NEWSECTION", 
           "STATEMENTBODY", "NEWINPUT", "NEWINCLUDE",
           "NEWDEF", "NEWLET", "NEWMATHOPERATOR",
           "NEWPROVIDECOMMAND", "NEWROBUSTCOMMAND"]