import os
from typing import Dict

def _insert_thmenvcapture_sty(
    envs_to_titles: Dict[str, str],
    src_dir: str
) -> str:
    """
    Simple version:
      - Wraps each theorem-like env using environ (\RenewEnviron)
      - Executes the body normally (so labels are set, counters increment, etc.)
      - Logs: env type, computed header (title + number + optional note), last label, and the raw body tokens.
      - Does NOT attempt to expand/sanitize body; only detokenizes at write-time.

    NOTE: This *still* uses environ, so xy-pic/xymatrix may still explode.
    This is intentionally the "back to basics" version you asked for.
    """
    header = r"""
\NeedsTeXFormat{LaTeX2e}
\ProvidesPackage{thmenvcapture}[2025/12/22 Theorem Environment Capturer]

\RequirePackage{environ}
\RequirePackage{etoolbox}
\RequirePackage{xparse}

\newwrite\envlog
\immediate\openout\envlog=thm-env-capture.log

\makeatletter

\def\thmenvcapture@lastlabel{}%
\def\thmenvcapture@star{*}%

% ---- log helper: do NOT expand body; detokenize at write-time only
\newcommand\thmenvcapture@log[4]{%
  \begingroup
    \immediate\write\envlog{BEGIN_ENV}%
    \immediate\write\envlog{type: #1}%
    \immediate\write\envlog{name: \expandafter\detokenize\expandafter{#2}}%
    \ifblank{#3}{}{%
      \immediate\write\envlog{label: #3}%
    }%
    \immediate\write\envlog{body: \expandafter\detokenize\expandafter{#4}}%
    \immediate\write\envlog{END_ENV}%
  \endgroup
}

% ---- label hook: records the last \label{...} seen inside the env
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

% Patch \newtheorem so we learn the counter each env uses,
% and then (if we already generated a wrapper macro) apply it.
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

% === Per-environment wrappers will be generated below ===
""".lstrip("\n")

    wrapper_blocks: list[str] = []

    for env, title in envs_to_titles.items():
        # IMPORTANT: no f-strings; build with concatenation to avoid brace escaping errors.
        block = (
            "% Wrapper for environment: " + env + " (" + title + ")\n"
            "\\newcommand\\thmenvcapture@wrap" + env + "{%\n"
            "  \\let\\thmenvcapture@orig@" + env + "\\" + env + "\n"
            "  \\let\\thmenvcapture@endorig@" + env + "\\end" + env + "\n"
            "  \\RenewEnviron{" + env + "}[1][]{%\n"
            "    \\global\\let\\thmenvcapture@lastlabel\\@empty\n"
            "    \\begingroup\n"
            "      % begin (steps counter)\n"
            "      \\ifblank{##1}{\\thmenvcapture@orig@" + env + "}{\\thmenvcapture@orig@" + env + "[##1]}%\n"
            "\n"
            "      % compute number\n"
            "      \\edef\\thmenvcapture@ctrname{\\thmenvcapture@getcounter{" + env + "}}%\n"
            "      \\edef\\LoggedNumber{%\n"
            "        \\ifx\\thmenvcapture@ctrname\\@empty\\@empty\\else\n"
            "          \\ifx\\thmenvcapture@ctrname\\thmenvcapture@star\\@empty\\else\n"
            "            \\csname the\\thmenvcapture@ctrname\\endcsname\n"
            "          \\fi\n"
            "        \\fi\n"
            "      }%\n"
            "\n"
            "      % run body normally (but record last \\label)\n"
            "      \\thmenvcapture@withlabelhook{\\BODY}%\n"
            "\n"
            "      % end\n"
            "      \\thmenvcapture@endorig@" + env + "\n"
            "\n"
            "      % build header + log raw body tokens (no expansion)\n"
            "      \\begingroup\n"
            "        \\let\\protect\\relax\n"
            "        \\edef\\LoggedName{\\detokenize\\expandafter{\\unexpanded\\expandafter{##1}}}%\n"
            "        \\edef\\LoggedHeader{" + title + " \\LoggedNumber}%\n"
            "        \\ifdefempty{\\LoggedName}{}{\\edef\\LoggedHeader{\\LoggedHeader\\space(\\LoggedName)}}%\n"
            "        \\edef\\LoggedLabel{\\thmenvcapture@lastlabel}%\n"
            "        \\thmenvcapture@log{" + env + "}{\\LoggedHeader}{\\LoggedLabel}{\\BODY}%\n"
            "      \\endgroup\n"
            "    \\endgroup\n"
            "  }%\n"
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