import os

def _insert_thmenvcapture_sty(
    envs_to_titles: dict[str, str],
    src_dir: str
) -> str:
    header = r"""
\NeedsTeXFormat{LaTeX2e}
\ProvidesPackage{thmenvcapture}[2025/12/10 Theorem Environment Capturer]

\RequirePackage{environ}
\RequirePackage{etoolbox}

\newwrite\envlog
\immediate\openout\envlog=thm-env-capture.log

\makeatletter

\def\thmenvcapture@lastlabel{}%

% Write a line where the payload is detokenized (so we don't expand macros).
% #1 = prefix (e.g. "name: ")
% #2 = token list to serialize
\newcommand\thmenvcapture@writedetok[2]{%
  \immediate\write\envlog{#1\expandafter\detokenize\expandafter{#2}}%
}

% Generic log helper (NO expansions):
%   #1 = type token list
%   #2 = name token list
%   #3 = label token list (may be empty)
%   #4 = body token list
\newcommand\thmenvcapture@log[4]{%
  \begingroup
    \immediate\write\envlog{BEGIN_ENV}%
    \thmenvcapture@writedetok{type: }{#1}%
    \thmenvcapture@writedetok{name: }{#2}%
    \ifdefempty{#3}{}{%
      \thmenvcapture@writedetok{label: }{#3}%
    }%
    \thmenvcapture@writedetok{body: }{#4}%
    \immediate\write\envlog{END_ENV}%
  \endgroup
}

% Run BODY with a label hook:
% capture \label{foo} into \thmenvcapture@lastlabel, while still doing normal \label.
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
            "    % typeset original environment; only pass optional arg if nonempty\n"
            "    \\ifdefempty{##1}{%\n"
            "      \\thmenvcapture@orig@" + env + "%\n"
            "    }{%\n"
            "      \\thmenvcapture@orig@" + env + "[##1]%\n"
            "    }%\n"
            "      \\thmenvcapture@withlabelhook{\\BODY}%\n"
            "    \\thmenvcapture@endorig@" + env + "\n"
            "    % log (NO expansions): name is just title + counter macro tokens + optional name tokens\n"
            "    \\begingroup\n"
            "      \\def\\LoggedType{" + env + "}%\n"
            "      \\def\\LoggedLabel{\\thmenvcapture@lastlabel}%\n"
            "      \\def\\LoggedName{" + title + " \\the" + env + " \\ifdefempty{##1}{}{(##1)}}%\n"
            "      \\thmenvcapture@log{\\LoggedType}{\\LoggedName}{\\LoggedLabel}{\\BODY}%\n"
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
    src_dir: str
):
    _insert_thmenvcapture_sty(envs_to_titles, src_dir)
    
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