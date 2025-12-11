import os
import re

def insert_thmenvcapture_sty(
    envs_to_titles: dict[str, str],
    src_dir: str
) -> str:
    # ----- Static header (your template, up to the per-env wrappers) -----
    header = r"""
\NeedsTeXFormat{LaTeX2e}
\ProvidesPackage{thmenvcapture}[2025/12/10 Theorem Environment Capturer]

\RequirePackage{environ}
\RequirePackage{etoolbox}

\newwrite\envlog
\immediate\openout\envlog=thm-env-capture.log

\makeatletter

% Store last label seen inside a theorem-like environment
\def\thmenvcapture@lastlabel{}%

% Generic log helper:
%   #1 = type (theorem/lemma/...)
%   #2 = name ("Theorem 1.2 (Name)")
%   #3 = label (may be empty)
%   #4 = the body tokens (\BODY) – we don't expand deeply
\newcommand\thmenvcapture@log[4]{%
  \begingroup
    \immediate\write\envlog{BEGIN_ENV}%
    \immediate\write\envlog{type: #1}%
    \immediate\write\envlog{name: #2}%
    \ifdefempty{#3}{}{%
      \immediate\write\envlog{label: #3}%
    }%
    \immediate\write\envlog{body: \expandafter\detokenize\expandafter{#4}}%
    \immediate\write\envlog{END_ENV}%
  \endgroup
}

% === Helper: run BODY with a label hook ===================================
% Locally patch \label so that any \label{foo} inside BODY sets
% \thmenvcapture@lastlabel=foo, while still doing the normal \label work.
\newcommand\thmenvcapture@withlabelhook[1]{%
  \begingroup
    \let\thmenvcapture@origlabel\label
    \def\label##1{%
      \gdef\thmenvcapture@lastlabel{##1}%
      \thmenvcapture@origlabel{##1}%
    }%
    #1%  <- BODY expands here with hooked \label
  \endgroup
}

% === Per-environment wrappers will be generated below ===
""".lstrip("\n")

    # ----- Dynamically generate one wrapper macro per env -----
    wrapper_blocks: list[str] = []

    for env, title in envs_to_titles.items():
        # Example: env="theorem", title="Theorem"
        # We build \thmenvcapture@wraptheorem, etc.
        block = (
            "% Wrapper for environment: " + env + " (" + title + ")\n"
            "\\newcommand\\thmenvcapture@wrap" + env + "{%\n"
            "  \\let\\thmenvcapture@orig@" + env + "\\" + env + "\n"
            "  \\let\\thmenvcapture@endorig@" + env + "\\end" + env + "\n"
            "  \\RenewEnviron{" + env + "}[1][]{%\n"
            "    % reset last label\n"
            "    \\global\\let\\thmenvcapture@lastlabel\\@empty\n"
            "    % typeset original environment with label hook around BODY\n"
            "    \\thmenvcapture@orig@" + env + "[##1]%\n"
            "      \\thmenvcapture@withlabelhook{\\BODY}%\n"
            "    \\thmenvcapture@endorig@" + env + "\n"
            "    % log\n"
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

    # ----- \AtBeginDocument hook: conditionally wrap each env -----
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

def inject_thmenvcapture(tex_path: str):
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