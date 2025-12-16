import os

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
\RequirePackage{xparse}

\newwrite\envlog
\immediate\openout\envlog=thm-env-capture.log

\makeatletter

\def\thmenvcapture@lastlabel{}%

\newcommand\thmenvcapture@log[4]{%
  \begingroup
    \immediate\write\envlog{BEGIN_ENV}%
    \immediate\write\envlog{type: #1}%
    \immediate\write\envlog{name: \expandafter\detokenize\expandafter{#2}}%
    \ifdefempty{#3}{}{%
      \immediate\write\envlog{label: #3}%
    }%
    \immediate\write\envlog{body: \expandafter\detokenize\expandafter{#4}}%
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
  \expandafter\gdef\csname thmenvcapture@ctr@#1\endcsname{*}%
}
\def\thmenvcapture@getcounter#1{%
  \@ifundefined{thmenvcapture@ctr@#1}{#1}{\csname thmenvcapture@ctr@#1\endcsname}%
}

\let\thmenvcapture@orig@newtheorem\newtheorem
\expandafter\let\csname thmenvcapture@orig@newtheorem*\endcsname\csname newtheorem*\endcsname

% Wrap \newtheorem: {env}[shared]{Title}[within]
\RenewDocumentCommand{\newtheorem}{m o m o}{%
  \IfNoValueTF{#2}{%
    \thmenvcapture@setcounter{#1}{#1}%
  }{%
    \thmenvcapture@setcounter{#1}{#2}%
  }%
  \IfNoValueTF{#2}{%
    \IfNoValueTF{#4}{%
      \thmenvcapture@orig@newtheorem{#1}{#3}%
    }{%
      \thmenvcapture@orig@newtheorem{#1}{#3}[#4]%
    }%
  }{%
    \IfNoValueTF{#4}{%
      \thmenvcapture@orig@newtheorem{#1}[#2]{#3}%
    }{%
      \thmenvcapture@orig@newtheorem{#1}[#2]{#3}[#4]%
    }%
  }%
}

% Wrap \newtheorem*: {env}{Title} (unnumbered)
\RenewDocumentCommand{\newtheorem*}{m m}{%
  \thmenvcapture@setunnumbered{#1}%
  \csname thmenvcapture@orig@newtheorem*\endcsname{#1}{#2}%
}

% --------------------------------------------------------------------
% Body expansion safety machinery (unchanged)
% --------------------------------------------------------------------
\newif\ifthmenvcapture@expandok
\def\thmenvcapture@bodystr{}%

\newcommand\thmenvcapture@checkunsafe[1]{%
  \thmenvcapture@expandoktrue
  \begingroup
    % Expand once before detokenizing so we scan the real body, not "\BODY"
    \edef\thmenvcapture@bodystr{\detokenize\expandafter{#1}}%
    \in@{\\begin}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\end}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\item}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\par}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi

    \in@{\\verb}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\Verbatim}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\verbatim}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\lstinline}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\lstlisting}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\mint}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\minted}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi

    \in@{\\footnote}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\footnotemark}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\footnotetext}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\marginpar}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\caption}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi

    \in@{\\label}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\ref}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\eqref}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\pageref}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\autoref}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\cref}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\Cref}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\hyperref}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\href}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\url}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\cite}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\citep}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\citet}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\index}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi

    \in@{\\input}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\include}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\includegraphics}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\openin}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\openout}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\read}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\write}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\write18}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\immediate}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi

    \in@{\\catcode}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\makeatletter}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\makeatother}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\def}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\edef}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\xdef}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\gdef}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\let}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\futurelet}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\expandafter}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\noexpand}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
  \endgroup
}

\newcommand\thmenvcapture@maybeexpandbody[2]{%
  % Fallback first: expand #2 once so passing \BODY stores the actual body tokens
  \expandafter\def\expandafter#1\expandafter{#2}%
  % Scan the fallback content (real body) for unsafe markers
  \thmenvcapture@checkunsafe{#1}%
  \ifthmenvcapture@expandok
    \begingroup
      \def\begin{\noexpand\begin}%
      \def\end{\noexpand\end}%
      \def\item{\noexpand\item}%
      \def\par{\noexpand\par}%

      % Freeze common reference/cite-like commands (prevents huge expansions)
      \def\ref{\noexpand\ref}%
      \def\eqref{\noexpand\eqref}%
      \def\pageref{\noexpand\pageref}%
      \def\cite{\noexpand\cite}%
      \def\citep{\noexpand\citep}%
      \def\citet{\noexpand\citet}%
      \def\href{\noexpand\href}%
      \def\url{\noexpand\url}%
      \def\hyperref{\noexpand\hyperref}%

      % Neutralize side-effects during expansion
      \let\label\@gobble
      \let\write\@gobbletwo
      \let\message\@gobble
      \let\typeout\@gobble
      \let\footnote\@gobble
      \let\marginpar\@gobble

      \protected@xdef#1{#2}%
    \endgroup
  \fi
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
            "    \\begingroup\n"
            "      % Begin theorem with/without optional arg exactly like user wrote it\n"
            "      \\ifdefempty{##1}{%\n"
            "        \\thmenvcapture@orig@" + env + "%\n"
            "      }{%\n"
            "        \\thmenvcapture@orig@" + env + "[##1]%\n"
            "      }%\n"
            "      \\edef\\thmenvcapture@ctrname{\\thmenvcapture@getcounter{" + env + "}}%\n"
            "      \\edef\\LoggedNumber{%\n"
            "        \\ifx\\thmenvcapture@ctrname\\@empty\\@empty\\else\n"
            "        \\ifx\\thmenvcapture@ctrname*\\@empty\\else\n"
            "          \\csname the\\thmenvcapture@ctrname\\endcsname\n"
            "        \\fi\\fi\n"
            "      }%\n"
            "      \\thmenvcapture@withlabelhook{\\BODY}%\n"
            "      \\thmenvcapture@endorig@" + env + "\n"
            "      \\begingroup\n"
            "        \\let\\protect\\relax\n"
            "        \\edef\\LoggedName{\\detokenize\\expandafter{\\unexpanded\\expandafter{##1}}}%\n"
            "        \\edef\\LoggedHeader{" + title + " \\LoggedNumber}%\n"
            "        \\ifdefempty{\\LoggedName}{}{\\edef\\LoggedHeader{\\LoggedHeader\\space(\\LoggedName)}}%\n"
            "        \\edef\\LoggedLabel{\\thmenvcapture@lastlabel}%\n"
            "        \\thmenvcapture@maybeexpandbody\\LoggedBody{\\BODY}%\n"
            "        \\thmenvcapture@log{" + env + "}{\\LoggedHeader}{\\LoggedLabel}{\\LoggedBody}%\n"
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