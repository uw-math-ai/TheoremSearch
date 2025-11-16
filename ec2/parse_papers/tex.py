import os, re
import glob
from .latex_parse import _scanner

DOC_CLASS_RE = re.compile(
    r"^[^%]*\\documentclass(\[.*?\])?\{.*?\}",
    re.MULTILINE
)

def find_main_tex_file(source_dir: str):
    """
    Robustly find the main .tex file in an extracted arXiv source.
    """
    candidates = []

    for root, _, files in os.walk(source_dir):
        for file in files:
            if file.endswith(".tex"):
                file_path = os.path.join(root, file)

                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        # read only first 200 lines; faster & covers 99.9%
                        head = "".join(f.readline() for _ in range(200))
                except Exception:
                    continue

                # actual preamble?
                if DOC_CLASS_RE.search(head):
                    return file_path   # definite main file

                # As backup: collect all .tex files to analyze further
                candidates.append(file_path)

    # If no documentclass found:
    # fallback: choose file that contains \begin{document}
    for path in candidates:
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                head = "".join(f.readline() for _ in range(200))
        except:
            continue
        if "\\begin{document}" in head:
            return path

    # If STILL nothing: default to largest file (most commonly the root)
    if candidates:
        return max(candidates, key=os.path.getsize)

    return None

def collect_imports(tarpath: str, file: str, pattern: str):
    """
    collects any tex that is imported into the main document, can include user-macros, sections, etc.
    """

    with open(file, "r+", encoding="utf-8", errors="ignore") as f:
        content = f.read()
        paper_imports = _scanner(pattern, content)
        if paper_imports:
            
            # check for multiple packages in a line
            pkgs = []
            for item in paper_imports:
                group = item.group('filepath')
                parts = [p.strip() for p in group.split(',')]
                pkgs.extend(parts)

            # place all valid packages
            for item in pkgs:
                if item[-4:] not in [".tex", ".sty", ".cls"]:
                    full_path = os.path.join(tarpath, item) + ".*"
                    file_matches = glob.glob(full_path)
                    if file_matches:
                        input_extension = file_matches[0][-4:]
                    else:
                        continue
                else:
                    input_extension = ""

                try:
                    with open(os.path.join(tarpath, item) + input_extension, encoding="utf-8", errors="ignore") as g:
                        preamble = g.read()
                        if rf"\input{item}" in content:
                            content = content.replace(rf"\input{{{item}}}", preamble)
                        elif rf"\usepackage{item}" in content:
                            content = content.replace(rf"\usepackage{{{item}}}", preamble) # this causes an error since multipackage imports cant fully be replaced
                        else:
                            content = preamble + content
                except Exception:
                    continue
            f.seek(0)
            f.write(content)
            f.truncate()
        else:
           pass