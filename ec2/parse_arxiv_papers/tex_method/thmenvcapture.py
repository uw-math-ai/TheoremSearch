import os
from typing import Dict

def _insert_thmenvcapture_sty(
    envs_to_titles: Dict[str, str],
    src_dir: str
) -> str:
    header = r"""
\NeedsTeXFormat{LaTeX2e}
\ProvidesPackage{thmenvcapture}[2025/12/27 Theorem Environment Capturer]

\RequirePackage{etoolbox}
\RequirePackage{xparse}

\newwrite\envlog
\immediate\openout\envlog=thm-env-capture.log

\makeatletter

\def\thmenvcapture@lastlabel{}%
\def\thmenvcapture@star{*}%

\newcommand\thmenvcapture@log[4]{%
  \begingroup
    \immediate\write\envlog{BEGIN_ENV}%
    \immediate\write\envlog{type: #1}%
    \immediate\write\envlog{name: \expandafter\detokenize\expandafter{#2}}%
    \immediate\write\envlog{body: \detokenize\expandafter{\unexpanded{#4}}}%
    \immediate\write\envlog{END_ENV}%
  \endgroup
}

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

% --------------------------------------------------------------------
% Map theorem-like env -> underlying counter name by hooking \newtheorem
% --------------------------------------------------------------------
\def\thmenvcapture@setcounter#1#2{%
  \expandafter\gdef\csname thmenvcapture@ctr@#1\endcsname{#2}%
}
\def\thmenvcapture@setunnumbered#1{%
  \expandafter\gdef\csname thmenvcapture@ctr@#1\endcsname{\thmenvcapture@star}%
}
\def\thmenvcapture@getcounter#1{%
  \@ifundefined{thmenvcapture@ctr@#1}{#1}{\csname thmenvcapture@ctr@#1\endcsname}%
}

\let\thmenvcapture@orig@newtheorem\newtheorem

\RenewDocumentCommand{\newtheorem}{s m o m o}{%
  \IfBooleanTF{#1}{%
    \thmenvcapture@setunnumbered{#2}%
    \thmenvcapture@orig@newtheorem*{#2}{#4}%
    \@ifundefined{thmenvcapture@wrap#2}{}{%
      \csname thmenvcapture@wrap#2\endcsname
    }%
  }{%
    \IfNoValueTF{#3}{%
      \thmenvcapture@setcounter{#2}{#2}%
    }{%
      \thmenvcapture@setcounter{#2}{#3}%
    }%
    \IfNoValueTF{#3}{%
      \IfNoValueTF{#5}{%
        \thmenvcapture@orig@newtheorem{#2}{#4}%
      }{%
        \thmenvcapture@orig@newtheorem{#2}{#4}[#5]%
      }%
    }{%
      \IfNoValueTF{#5}{%
        \thmenvcapture@orig@newtheorem{#2}[#3]{#4}%
      }{%
        \thmenvcapture@orig@newtheorem{#2}[#3]{#4}[#5]%
      }%
    }%
    \@ifundefined{thmenvcapture@wrap#2}{}{%
      \csname thmenvcapture@wrap#2\endcsname
    }%
  }%
}
""".lstrip("\n")

    wrapper_blocks: list[str] = []

    for env, title in envs_to_titles.items():
        block = (
            "% Wrapper for environment: " + env + " (" + title + ")\n"
            "\\newcommand\\thmenvcapture@wrap" + env + "{%\n"
            "  \\let\\thmenvcapture@orig@" + env + "\\" + env + "\n"
            "  \\let\\thmenvcapture@endorig@" + env + "\\end" + env + "\n"
            "  \\RenewDocumentEnvironment{" + env + "}{ O{} +b }{%\n"
            "    \\global\\let\\thmenvcapture@lastlabel\\@empty\n"
            "    \\begingroup\n"
            "      \\ifblank{#1}{\\thmenvcapture@orig@" + env + "}{\\thmenvcapture@orig@" + env + "[#1]}%\n"
            "\n"
            "      \\edef\\thmenvcapture@ctrname{\\thmenvcapture@getcounter{" + env + "}}%\n"
            "      \\edef\\LoggedNumber{%\n"
            "        \\ifx\\thmenvcapture@ctrname\\@empty\\@empty\\else\n"
            "          \\ifx\\thmenvcapture@ctrname\\thmenvcapture@star\\@empty\\else\n"
            "            \\csname the\\thmenvcapture@ctrname\\endcsname\n"
            "          \\fi\n"
            "        \\fi\n"
            "      }%\n"
            "\n"
            "      \\thmenvcapture@endorig@" + env + "\n"
            "\n"
            "      \\begingroup\n"
            "        \\let\\protect\\relax\n"
            "        \\edef\\LoggedName{\\detokenize\\expandafter{\\unexpanded\\expandafter{#1}}}%\n"
            "        \\edef\\LoggedHeader{" + title + " \\LoggedNumber}%\n"
            "        \\ifdefempty{\\LoggedName}{}{\\edef\\LoggedHeader{\\LoggedHeader\\space(\\LoggedName)}}%\n"
            "        \\edef\\LoggedLabel{\\thmenvcapture@lastlabel}%\n"
            "        \\thmenvcapture@log{" + env + "}{\\LoggedHeader}{\\LoggedLabel}{#2}%\n"
            "      \\endgroup\n"
            "    \\endgroup\n"
            "  }{}%\n"
            "}%\n\n"
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

    return sty_text

def inject_thmenvcapture(
    tex_path: str,
    envs_to_titles: dict[str, str],
    src_dir: str
):
    thmenvcapture_content = _insert_thmenvcapture_sty(envs_to_titles, src_dir)
    
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

    return thmenvcapture_content