import os
import textwrap
from typing import List
import subprocess
import hashlib
from pathlib import Path

def generate_dummy_biblatex(workdir: str):
    sty_path = os.path.join(workdir, "biblatex.sty")
    if os.path.exists(sty_path):
        return

    dummy = textwrap.dedent(r"""
    %% biblatex.sty -- dummy stub generated for theorem capture
    \NeedsTeXFormat{LaTeX2e}
    \ProvidesPackage{biblatex}[2025/12/11 Dummy stub]

    % Make core biblatex commands no-ops:
    \newcommand\addbibresource[2][]{}
    \newcommand\printbibliography[1][]{}
    \newcommand\DeclareFieldFormat[2]{}
    \newcommand\AtEveryBibitem[1]{}

    \endinput
    """).lstrip("\n")

    with open(sty_path, "w", encoding="utf-8") as f:
        f.write(dummy)


def _generate_dummy_package(pkg_name: str, workdir: str):
    sty_path = os.path.join(workdir, f"{pkg_name}.sty")
    if os.path.exists(sty_path):
        return
    
    dummy = textwrap.dedent(rf"""
    %% {pkg_name}.sty -- dummy stub generated for theorem capture
    \NeedsTeXFormat{{LaTeX2e}}
    \ProvidesPackage{{{pkg_name}}}[2025/12/11 Dummy stub]

    %% Add no-op command definitions here if this package normally defines anything
    %% For now, we just provide an empty package.

    \endinput
    """).lstrip("\n")

    with open(sty_path, "w", encoding="utf-8") as f:
        f.write(dummy)

    return sty_path


def _hash_file(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return ""
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def run_pdflatex(
    main_tex_name: str,
    cwd: str,
    timeout: int,
    missing_pkgs: List[str] = None
) -> str:
    if missing_pkgs is None:
        missing_pkgs = []

    for pkg in missing_pkgs:
        _generate_dummy_package(pkg, cwd)

    aux_path = os.path.join(cwd, f"{Path(main_tex_name).stem}.aux")
    last_aux_hash = None
    out_all: List[str] = []

    for _ in range(5):
        cmd = [
            "pdflatex",
            "-draftmode",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            "-recorder",
            main_tex_name
        ]
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout
        )
        out = proc.stdout
        out_all.append(out)

        new_missing_pkgs: List[str] = []
        for line in out.splitlines():
            if "File `" in line and ".sty' not found" in line:
                pkg = line.split("File `", 1)[1].split(".sty", 1)[0]
                if pkg != "thmenvcapture":
                    new_missing_pkgs.append(pkg)

        if new_missing_pkgs:
            return run_pdflatex(
                main_tex_name,
                cwd,
                timeout,
                new_missing_pkgs
            )

        if proc.returncode != 0:
            break

        aux_hash = _hash_file(aux_path)
        if aux_hash == last_aux_hash:
            break
        last_aux_hash = aux_hash

    return "\n\n".join(out_all)