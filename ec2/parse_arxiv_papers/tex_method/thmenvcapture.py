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

\newwrite\envlog
\immediate\openout\envlog=thm-env-capture.log

\makeatletter

% Store last label seen inside a theorem-like environment
\def\thmenvcapture@lastlabel{}%

% Generic log helper:
%   #1 = type (theorem/lemma/...)
%   #2 = name ("Theorem 1.2 (Name)")
%   #3 = label (may be empty)
%   #4 = body tokens (we detokenize at write-time; no expansion during \write)
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
% Capture any \label{foo} into \thmenvcapture@lastlabel, while still doing normal \label.
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

% === Expand-or-fallback for body ==========================================
% Goal:
%   - NEVER produce empty body
%   - Attempt best-effort expansion only when body looks "safe"
%   - Otherwise fall back to raw BODY (as before)
%
% Usage: \thmenvcapture@maybeexpandbody\Dest{<BODY tokens>}
%
% Mechanism:
%   - First, set \Dest to raw BODY (fallback guaranteed).
%   - Then detokenize BODY into a string and scan for "unsafe" markers.
%   - Only if no unsafe markers, attempt \protected@xdef expansion with frozen structure tokens.
%
\newif\ifthmenvcapture@expandok
\def\thmenvcapture@bodystr{}%

\newcommand\thmenvcapture@checkunsafe[1]{%
  \thmenvcapture@expandoktrue
  \begingroup
    \edef\thmenvcapture@bodystr{\detokenize{#1}}%
    % Heuristic "unsafe" markers (conservative by design)
    \in@{\\begin}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\end}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\item}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\par}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\verb}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\Verbatim}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\lstinline}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\mint}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\footnote}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\marginpar}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\cite}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\ref}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\eqref}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\input}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\include}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
    \in@{\\includegraphics}{\thmenvcapture@bodystr}\ifin@\global\thmenvcapture@expandokfalse\fi
  \endgroup
}

\newcommand\thmenvcapture@maybeexpandbody[2]{%
  % Fallback first: guarantees body is never empty
  \def#1{#2}%
  % Decide whether to attempt expansion
  \thmenvcapture@checkunsafe{#2}%
  \ifthmenvcapture@expandok
    \begingroup
      % Freeze common structure tokens so xdef doesn't try to "run" them
      \def\begin{\noexpand\begin}%
      \def\end{\noexpand\end}%
      \def\item{\noexpand\item}%
      \def\par{\noexpand\par}%
      % Neutralize common side-effect macros during forced expansion
      \let\label\@gobble
      \let\write\@gobbletwo
      \let\message\@gobble
      \let\typeout\@gobble
      \let\footnote\@gobble
      \let\marginpar\@gobble
      % Respect robust/protected macros
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
            "    \\thmenvcapture@orig@" + env + "[##1]%\n"
            "      \\thmenvcapture@withlabelhook{\\BODY}%\n"
            "    \\thmenvcapture@endorig@" + env + "\n"
            "    \\begingroup\n"
            "      \\protected@edef\\LoggedName{##1}%\n"
            "      \\protected@edef\\LoggedHeader{" + title + " \\the" + env + "%\n"
            "        \\ifdefempty{\\LoggedName}{}{ (\\LoggedName)}}%\n"
            "      \\edef\\LoggedLabel{\\thmenvcapture@lastlabel}%\n"
            "      \\thmenvcapture@maybeexpandbody\\LoggedBody{\\BODY}%\n"
            "      \\thmenvcapture@log{" + env + "}{\\LoggedHeader}{\\LoggedLabel}{\\LoggedBody}%\n"
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