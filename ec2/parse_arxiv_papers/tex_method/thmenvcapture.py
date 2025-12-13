import os
from typing import Dict

def _insert_thmenvcapture_sty(
    envs_to_titles: Dict[str, str],
    src_dir: str,
    expand_macros: bool,
) -> str:
    header = r"""
\NeedsTeXFormat{LaTeX2e}
\ProvidesPackage{thmenvcapture}[2025/12/10 Theorem Environment Capturer]

\RequirePackage{environ}
\RequirePackage{etoolbox}

\newwrite\envlog
\immediate\openout\envlog=thm-env-capture.log

\makeatletter

% Toggle macro expansion in logged body (set by generator)
\newif\ifthmenvcapture@expandmacros
""".lstrip("\n")

    header += ("\\thmenvcapture@expandmacrostrue\n" if expand_macros
               else "\\thmenvcapture@expandmacrosfalse\n")

    header += r"""

% Store last label seen inside a theorem-like environment
\def\thmenvcapture@lastlabel{}%

% --- Best-effort sandbox to reduce dangerous side-effects during expansion ---
\newcommand\thmenvcapture@sandbox{%
  \let\input\relax
  \let\include\relax
  \let\openin\relax
  \let\openout\relax
  \let\read\relax
  \let\write\relax
  \@ifundefined{write18}{}{\let\write18\relax}%
  \let\loop\relax
  \let\repeat\relax
}

% Prepare the body string to log into \thmenvcapture@bodytolog
% If expandmacros is on, try a protected expansion; otherwise keep tokens as-is.
\def\thmenvcapture@bodytolog{}%
\newcommand\thmenvcapture@preparebody[1]{%
  \begingroup
    \ifthmenvcapture@expandmacros
      \thmenvcapture@sandbox
      \let\protect\noexpand
      \protected@edef\thmenvcapture@tmp{#1}%
      \xdef\thmenvcapture@bodytolog{\thmenvcapture@tmp}%
    \else
      \xdef\thmenvcapture@bodytolog{#1}%
    \fi
  \endgroup
}

% Generic log helper:
%   #1 = type (theorem/lemma/...)
%   #2 = name ("Theorem 1.2 (Name)")
%   #3 = label (may be empty)
%   #4 = the body tokens (\BODY)
\newcommand\thmenvcapture@log[4]{%
  \begingroup
    \thmenvcapture@preparebody{#4}%
    \immediate\write\envlog{BEGIN_ENV}%
    \immediate\write\envlog{type: #1}%
    \immediate\write\envlog{name: #2}%
    \ifdefempty{#3}{}{%
      \immediate\write\envlog{label: #3}%
    }%
    \immediate\write\envlog{body: \expandafter\detokenize\expandafter{\thmenvcapture@bodytolog}}%
    \immediate\write\envlog{END_ENV}%
  \endgroup
}

% === Helper: run BODY with a label hook ===================================
\newcommand\thmenvcapture@withlabelhook[1]{%
  \begingroup
    \let\thmenvcapture@origlabel\label
    \def\label##1{%
      \gdef\thmenvcapture@lastlabel{##1}%
      \thmenvcapture@origlabel{##1}%
    }%
    #1%
  \endgroup
}

% === Per-environment wrappers will be generated below ===
""".lstrip("\n")

    wrapper_blocks: list[str] = []
    for env, title in envs_to_titles.items():
        block = (
            "% Wrapper for environment: " + env + " (" + title + ")\n"
            "\\newcommand\\thmenvcapture@wrap" + env + "{%\n"
            "  \\let\\thmenvcapture@orig@" + env + "\\" + env + "\n"
            "  \\let\\thmenvcapture@endorig@" + env + "\\end" + env + "\n"
            "  \\RenewEnviron{" + env + "}[1][]{%\n"
            "    \\global\\let\\thmenvcapture@lastlabel\\@empty\n"
            "    \\thmenvcapture@orig@" + env + "[##1]%\n"
            "      \\thmenvcapture@withlabelhook{\\BODY}%\n"
            "    \\thmenvcapture@endorig@" + env + "\n"
            "    \\begingroup\n"
            "      \\protected@edef\\LoggedName{##1}%\n"
            "      \\edef\\LoggedHeader{" + title + " \\the" + env + "%\n"
            "        \\ifdefempty{\\LoggedName}{}{ (\\LoggedName)}}%\n"
            "      \\edef\\LoggedLabel{\\thmenvcapture@lastlabel}%\n"
            "      \\thmenvcapture@log{" + env + "}{\\LoggedHeader}{\\LoggedLabel}{\\BODY}%\n"
            "    \\endgroup\n"
            "  }%\n"
            "}\n\n"
        )
        wrapper_blocks.append(block)

    wrappers = "".join(wrapper_blocks)

    at_begin_lines: list[str] = ["\\AtBeginDocument{%\n"]
    for env in envs_to_titles:
        at_begin_lines.append(
            "  \\@ifundefined{" + env + "}{}{%\n"
            "    \\thmenvcapture@wrap" + env + "\n"
            "  }%\n"
        )
    at_begin_lines.append("}%\n")
    at_begin = "".join(at_begin_lines)

    footer = "\n\\makeatother\n\\endinput\n"

    sty_text = header + wrappers + at_begin + footer
    sty_path = os.path.join(src_dir, "thmenvcapture.sty")

    with open(sty_path, "w", encoding="utf-8") as f:
        f.write(sty_text)

    return sty_path

def inject_thmenvcapture(
    tex_path: str,
    envs_to_titles: dict[str, str],
    src_dir: str,
    expand_macros: bool = False
):
    _insert_thmenvcapture_sty(envs_to_titles, src_dir, expand_macros)
    
    with open(tex_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    if r"\usepackage{thmenvcapture}" in content:
        return  # already injected

    new_content = content.replace(
        "\\begin{document}",
        "\\usepackage{thmenvcapture}\n\\begin{document}",
        1,
    )

    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(new_content)