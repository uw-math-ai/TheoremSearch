import os
import glob
from .latex_parse import _scanner

def find_main_tex_file(source_dir: str):
    """
    Finds the main .tex file in a directory by looking for '\\documentclass'.
    """
    for root, _, files in os.walk(source_dir):
        for file in files:
            if file.endswith(".tex"):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        if r"\documentclass" in f.read() and r"%\documentclass" not in f.read(): # might need its own regex ptrn
                            # print(f"Found main .tex file: {file_path}")
                            return file_path
                except Exception:
                    continue
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