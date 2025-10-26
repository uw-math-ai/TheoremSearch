"""
Helpers to manipulate local .tex files.
"""

import os
import glob
from latex_parse import _scanner

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
                        if r"\documentclass" in f.read():
                            print(f"Found main .tex file: {file_path}")
                            return file_path
                except Exception:
                    continue
    return None

def collect_imports(import_appends: str, tarpath: str, content: str, pattern: str):
    """
    collects any tex that is imported into the main document, can include user-macros, sections, etc.
    """
    paper_imports = _scanner(pattern, content)
    if paper_imports:
        for item in paper_imports:
            if item.group('filepath')[-4:] not in [".tex", ".sty", ".cls"]:
                full_path = os.path.join(tarpath, item.group('filepath')) + ".*"
                file_matches = glob.glob(full_path)
                if file_matches:
                    input_extension = file_matches[0][-4:]
                else:
                    continue
            else:
                input_extension = ""
            with open(os.path.join(tarpath, item.group('filepath')) + input_extension, encoding="utf-8", errors="ignore") as g:
                preamble = g.read()
            import_appends = preamble + import_appends
        return import_appends
    else:
        return import_appends
        
  