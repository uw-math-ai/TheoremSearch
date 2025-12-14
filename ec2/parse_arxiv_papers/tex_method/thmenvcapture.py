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

% Write a line with a detokenized payload (does not expand during \write).
% #1 = prefix text, #2 = token list (already expanded if desired)
\newcommand\thmenvcapture@writedetok[2]{%
  \immediate\write\envlog{#1\expandafter\detokenize\expandafter{#2}}%
}

% Log helper:
%   #1 = type tokens (not expanded)
%   #2 = expanded name/header tokens (we detokenize when writing)
%   #3 = expanded label tokens (may be empty)
%   #4 = body token list (NO expansion; detokenize)
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

% Run BODY with a label hook: capture \label{...} argument.
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

% Expand metadata safely (NOT body). Result survives group.
% Usage: \thmenvcapture@metaedef\Dest{<tokens>}
\newcommand\thmenvcapture@metaedef[2]{%
  \begingroup
    \let\protect\noexpand
    \let\write\@gobbletwo
    \let\message\@gobble
    \let\typeout\@gobble
    \global\protected@edef#1{#2}%
  \endgroup
}

% === Per-environment wrappers will be generated below ===
""".lstrip("\n")

    wrapper_blocks: list[str] = []

    for env, title in envs_to_titles.items():
        # Name counter macro: \the<env> i.e. \thetheorem; use \csname
        block = (
            "% Wrapper for environment: " + env + " (" + title + ")\n"
            "\\newcommand\\thmenvcapture@wrap" + env + "{%\n"
            "  \\let\\thmenvcapture@orig@" + env + "\\" + env + "\n"
            "  \\let\\thmenvcapture@endorig@" + env + "\\end" + env + "\n"
            "  \\RenewEnviron{" + env + "}[1][]{%\n"
            "    \\global\\let\\thmenvcapture@lastlabel\\@empty\n"
            "    % typeset original env; only pass optional arg if nonempty\n"
            "    \\ifdefempty{##1}{%\n"
            "      \\thmenvcapture@orig@" + env + "%\n"
            "    }{%\n"
            "      \\thmenvcapture@orig@" + env + "[##1]%\n"
            "    }%\n"
            "      \\thmenvcapture@withlabelhook{\\BODY}%\n"
            "    \\thmenvcapture@endorig@" + env + "\n"
            "    % --- build expanded metadata (name + label), but NEVER expand BODY ---\n"
            "    \\begingroup\n"
            "      \\def\\LoggedType{" + env + "}%\n"
            "      \\thmenvcapture@metaedef\\LoggedLabel{\\thmenvcapture@lastlabel}%\n"
            "      \\thmenvcapture@metaedef\\LoggedHeader{"
                + title + " \\csname the" + env + "\\endcsname"
                + "\\ifdefempty{##1}{}{ (##1)}"
            + "}%\n"
            "      \\thmenvcapture@log{\\LoggedType}{\\LoggedHeader}{\\LoggedLabel}{\\BODY}%\n"
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