import os

def _insert_thmenvcapture_sty(
    envs_to_titles: dict[str, str],
    src_dir: str
) -> str:
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

% --------------------------------------------------------------------
% "Troublesome" detection:
% If the theorem body CONTAINS any of these substrings, we DO NOT EXECUTE
% \BODY (prevents undefined control sequences). We STILL LOG the exact
% original body text (unexpanded).
%
% This is the key behavior you want:
%   (1) Try to execute body unless flagged troublesome.
%   (2) If flagged troublesome -> NEVER execute; log exact text anyway.
% --------------------------------------------------------------------
\newif\ifthmenvcapture@skipbody
\def\thmenvcapture@bodystr{}%

% Expand once into a detokenized string and search it.
\newcommand\thmenvcapture@checktroublesome[1]{%
  \global\thmenvcapture@skipbodyfalse
  \begingroup
    \edef\thmenvcapture@bodystr{\detokenize\expandafter{#1}}%

    % --- TikZ / PGF / commutative diagrams ---
    \in@{\\begin{tikzpicture}}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@skipbodytrue\fi
    \in@{\\end{tikzpicture}}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@skipbodytrue\fi
    \in@{\\begin{tikzcd}}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@skipbodytrue\fi
    \in@{\\end{tikzcd}}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@skipbodytrue\fi
    \in@{\\tikzcdset}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@skipbodytrue\fi
    \in@{\\usetikzlibrary}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@skipbodytrue\fi
    \in@{\\tikzset}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@skipbodytrue\fi
    \in@{\\tikz}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@skipbodytrue\fi
    \in@{\\pgf}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@skipbodytrue\fi
    \in@{\\pgfplots}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@skipbodytrue\fi
    \in@{\\begin{axis}}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@skipbodytrue\fi
    \in@{\\end{axis}}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@skipbodytrue\fi

    % --- Verbatim / code-like (often explodes under stubs) ---
    \in@{\\begin{minted}}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@skipbodytrue\fi
    \in@{\\end{minted}}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@skipbodytrue\fi
    \in@{\\mintinline}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@skipbodytrue\fi
    \in@{\\begin{lstlisting}}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@skipbodytrue\fi
    \in@{\\end{lstlisting}}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@skipbodytrue\fi
    \in@{\\lstinline}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@skipbodytrue\fi
    \in@{\\begin{Verbatim}}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@skipbodytrue\fi
    \in@{\\end{Verbatim}}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@skipbodytrue\fi
    \in@{\\verb}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@skipbodytrue\fi
  \endgroup
}

% --------------------------------------------------------------------
% Body expansion safety:
% Always starts with the exact original body tokens.
% If deemed safe, replaces with a protected expansion.
% If unsafe, leaves exact text unchanged.
% --------------------------------------------------------------------
\newif\ifthmenvcapture@expandok

\newcommand\thmenvcapture@checkunsafe[1]{%
  \thmenvcapture@expandoktrue
  \begingroup
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
  % Always start with exact original tokens
  \expandafter\def\expandafter#1\expandafter{#2}%
  % Attempt safe protected expansion; if unsafe, leave as exact original text.
  \thmenvcapture@checkunsafe{#1}%
  \ifthmenvcapture@expandok
    \begingroup
      \def\begin{\noexpand\begin}%
      \def\end{\noexpand\end}%
      \def\item{\noexpand\item}%
      \def\par{\noexpand\par}%

      \def\ref{\noexpand\ref}%
      \def\eqref{\noexpand\eqref}%
      \def\pageref{\noexpand\pageref}%
      \def\cite{\noexpand\cite}%
      \def\citep{\noexpand\citep}%
      \def\citet{\noexpand\citet}%
      \def\href{\noexpand\href}%
      \def\url{\noexpand\url}%
      \def\hyperref{\noexpand\hyperref}%

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
            "      \\ifblank{##1}{%\n"
            "        \\thmenvcapture@orig@" + env + "%\n"
            "      }{%\n"
            "        \\thmenvcapture@orig@" + env + "[##1]%\n"
            "      }%\n"
            "      \\edef\\thmenvcapture@ctrname{\\thmenvcapture@getcounter{" + env + "}}%\n"
            "      \\edef\\LoggedNumber{%\n"
            "        \\ifx\\thmenvcapture@ctrname\\@empty\\@empty\\else\n"
            "          \\ifx\\thmenvcapture@ctrname\\thmenvcapture@star\\@empty\\else\n"
            "            \\csname the\\thmenvcapture@ctrname\\endcsname\n"
            "          \\fi\n"
            "        \\fi\n"
            "      }%\n"
            "\n"
            "      % If the body looks troublesome, DO NOT execute it.\n"
            "      % Otherwise, execute it (and hook \\label).\n"
            "      \\thmenvcapture@checktroublesome{\\BODY}%\n"
            "      \\ifthmenvcapture@skipbody\n"
            "        % intentionally skip executing \\BODY\n"
            "      \\else\n"
            "        \\thmenvcapture@withlabelhook{\\BODY}%\n"
            "      \\fi\n"
            "\n"
            "      \\thmenvcapture@endorig@" + env + "\n"
            "      \\begingroup\n"
            "        \\let\\protect\\relax\n"
            "        \\edef\\LoggedName{\\detokenize\\expandafter{\\unexpanded\\expandafter{##1}}}%\n"
            "        \\edef\\LoggedHeader{" + title + " \\LoggedNumber}%\n"
            "        \\ifdefempty{\\LoggedName}{}{\\edef\\LoggedHeader{\\LoggedHeader\\space(\\LoggedName)}}%\n"
            "        \\edef\\LoggedLabel{\\thmenvcapture@lastlabel}%\n"
            "\n"
            "        % Always log exact original text; try safe expansion; if unsafe, remains exact.\n"
            "        \\thmenvcapture@maybeexpandbody\\LoggedBody{\\BODY}%\n"
            "\n"
            "        \\thmenvcapture@log{" + env + "}{\\LoggedHeader}{\\LoggedLabel}{\\LoggedBody}%\n"
            "      \\endgroup\n"
            "    \\endgroup\n"
            "  }%\n"
            "}%\n\n"
        )
        wrapper_blocks.append(block)

    wrappers = "".join(wrapper_blocks)

    disable_lines: list[str] = ["\\newcommand\\thmenvcapture@disablewrappers{%\n"]
    for env in envs_to_titles:
        disable_lines.append(
            "  \\@ifundefined{thmenvcapture@orig@" + env + "}{}{%\n"
            "    \\let\\" + env + "\\thmenvcapture@orig@" + env + "\n"
            "    \\let\\end" + env + "\\thmenvcapture@endorig@" + env + "\n"
            "  }%\n"
        )
    disable_lines.append("}%\n")
    disable_block = "".join(disable_lines)

    at_begin_lines: list[str] = ["\\AtBeginDocument{%\n"]
    for env in envs_to_titles:
        at_begin_lines.append(
            "  \\@ifundefined{" + env + "}{}{%\n"
            "    \\thmenvcapture@wrap" + env + "\n"
            "  }%\n"
        )
    at_begin_lines.append("}%\n")
    at_begin = "".join(at_begin_lines)

    # ---- Guards: environments inside which we temporarily disable wrappers ----
    guard_envs = [
        "restatable",
        "restatable*",
        "restate",
        "restate*",
        "thmrestate",
        "thmrestate*",
        "repeatthm",
        "repeatthm*",
        "repeatedthm",
        "repeatedthm*",
        "namedtheorem",
        "namedtheorem*"
    ]

    guard_lines: list[str] = []
    for g in guard_envs:
        guard_lines.append(
            "\\@ifundefined{" + g + "}{}{%\n"
            "  \\AtBeginEnvironment{" + g + "}{\\begingroup\\thmenvcapture@disablewrappers}\n"
            "  \\AtEndEnvironment{" + g + "}{\\endgroup}\n"
            "}\n"
        )
    guards = "".join(guard_lines)

    footer = "\n\\makeatother\n\\endinput\n"

    sty_text = header + wrappers + disable_block + at_begin + guards + footer
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