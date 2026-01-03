from typing import Dict
from pathlib import Path
from ...enums import Mode

def _insert_thmenvcapture_sty(
    paper_dir: Path,
    theorem_envs: Dict[str, str]
):
    header = r"""
\NeedsTeXFormat{LaTeX2e}
\ProvidesPackage{thmenvcapture}[2026/01/02 Theorem Environment Capturer]

\RequirePackage{etoolbox}
\RequirePackage{xparse}

\newwrite\envlog
\immediate\openout\envlog=thm-env-capture.log

\makeatletter

\def\thmenvcapture@star{*}%

% ------------------------------------------------------------
% Logging helpers
%  - raw: NO expansion (good for note/body/env)
%  - exp: expands ONCE (good for computed number)
% ------------------------------------------------------------

\def\thmenvcapture@writefieldraw#1#2{%
  \begingroup
    \immediate\write\envlog{#1: \detokenize\expandafter{\unexpanded{#2}}}%
  \endgroup
}

\def\thmenvcapture@writefieldexp#1#2{%
  \begingroup
    \edef\thmenvcapture@tmp{#2}%
    \immediate\write\envlog{#1: \thmenvcapture@tmp}%
  \endgroup
}

\def\thmenvcapture@logblock#1#2#3#4{%
  % #1 env, #2 ref(number), #3 note, #4 body
  \begingroup
    \immediate\write\envlog{BEGIN_ENV}%
    \thmenvcapture@writefieldraw{env}{#1}%
    \thmenvcapture@writefieldexp{ref}{#2}%
    \thmenvcapture@writefieldraw{note}{#3}%
    \thmenvcapture@writefieldraw{body}{#4}%
    \immediate\write\envlog{END_ENV}%
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

    for env, title in theorem_envs.items():
        block = (
            "% Wrapper for environment: " + env + " (" + title + ")\n"
            "\\newcommand\\thmenvcapture@wrap" + env + "{%\n"
            "  \\let\\thmenvcapture@orig@" + env + "\\" + env + "\n"
            "  \\let\\thmenvcapture@endorig@" + env + "\\end" + env + "\n"
            "  \\RenewDocumentEnvironment{" + env + "}{ O{} +b }{%\n"
            "    \\begingroup\n"
            "      \\ifblank{##1}{\\thmenvcapture@orig@" + env + "}{\\thmenvcapture@orig@" + env + "[##1]}%\n"
            "\n"
            "      \\edef\\thmenvcapture@ctrname{\\thmenvcapture@getcounter{" + env + "}}%\n"
            "      \\def\\thmenvcapture@num{}%\n"
            "      \\begingroup\n"
            "        \\ifx\\thmenvcapture@ctrname\\@empty\n"
            "        \\else\n"
            "          \\ifx\\thmenvcapture@ctrname\\thmenvcapture@star\n"
            "          \\else\n"
            "            \\protected@edef\\thmenvcapture@num{\\csname the\\thmenvcapture@ctrname\\endcsname}%\n"
            "          \\fi\n"
            "        \\fi\n"
            "        \\global\\let\\thmenvcapture@num\\thmenvcapture@num\n"
            "      \\endgroup\n"
            "\n"
            "      \\thmenvcapture@endorig@" + env + "\n"
            "\n"
            "      \\thmenvcapture@logblock{" + env + "}{\\thmenvcapture@num}{##1}{##2}%\n"
            "    \\endgroup\n"
            "  }{}%\n"
            "}%\n\n"
        )
        wrapper_blocks.append(block)

    wrappers = "".join(wrapper_blocks)

    at_begin_lines: list[str] = ["\\AtBeginDocument{%\n"]
    for env in theorem_envs:
        at_begin_lines.append(
            "  \\@ifundefined{" + env + "}{}{%\n"
            "    \\thmenvcapture@wrap" + env + "\n"
            "  }%\n"
        )
    at_begin_lines.append("}%\n")
    at_begin = "".join(at_begin_lines)

    footer = "\n\\makeatother\n\\endinput\n"

    sty_text = header + wrappers + at_begin + footer
    sty_path = paper_dir / "thmenvcapture.sty"
    sty_path.write_text(sty_text, encoding="utf-8")

def inject_thmenvcapture(
    main_file: Path,
    paper_dir: Path,
    theorem_envs: Dict[str, str],
    mode: Mode
):
    r"""
    Injects a working `\usepackage{thmenvcapture}` into the main file. The LaTeX package creates
    `thmenvcapture.log`, a JSONL-like file that captures the env, ref, note, and body of theorems.

    Parameters
    ----------
    main_file : Path
        Path to main file
    paper_dir : Path
        Paper's source files
    theorem_envs : Dict[str, str]
        Dict mapping theorem environments to their types
    mode : Mode
        Mode to run `inject_thmenvcapture` in
    """

    _insert_thmenvcapture_sty(paper_dir, theorem_envs)
    
    with open(main_file, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    if r"\documentstyle" in content: # handle older LaTeX versions
        new_content = content.replace(
            "\\begin{document}",
            "\n\\input{thmenvcapture.sty}\n\\begin{document}",
            1,
        )
    else:
        new_content = content.replace(
            "\\begin{document}",
            "\n\\usepackage{thmenvcapture}\n\\begin{document}",
            1,
        )

        if r"\documentclass" not in content and mode == Mode.DEBUGGING:
            print(f"[DEBUG] Neither `\documentstyle` nor `\documentclass` exist in main file")
        

    with open(main_file, "w", encoding="utf-8") as f:
        f.write(new_content)