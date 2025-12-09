import os, re
import glob
from .latex_parse import _scanner

DOC_CLASS_RE = re.compile(
    r"^[^%]*\\documentclass(\[.*?\])?\{.*?\}",
    re.MULTILINE
)

IMPORT_RE = re.compile(
    r"\\(input|include|subfile|usepackage)\s*(?:\[[^\]]*\])?\s*\{(?P<filepath>[^}]*)\}"
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
                        head = "".join(f.readline() for _ in range(200))
                except Exception:
                    continue

                if DOC_CLASS_RE.search(head):
                    return file_path

                candidates.append(file_path)

    for path in candidates:
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                head = "".join(f.readline() for _ in range(200))
        except:
            continue
        if "\\begin{document}" in head:
            return path

    if candidates:
        return max(candidates, key=os.path.getsize)

    return None

def collect_imports(tarpath: str, file: str, pattern: str):
    """
    collects any tex that is imported into the main document, can include user-macros, sections, etc.
    """
    processed = set()
    cache = {}

    def resolve_content(cur_file: str, content: str) -> str:
        matches = list(IMPORT_RE.finditer(content))
        if not matches:
            return content

        for m in matches:
            group = m.group('filepath')
            parts = [p.strip() for p in group.split(',') if p.strip()]
            cmd = m.group(1)

            for name in parts:
                base_dir = os.path.dirname(cur_file) or tarpath
                candidates = []
                if name.endswith((".tex", ".sty", ".cls")):
                    candidates.append(os.path.join(base_dir, name))
                else:
                    full_path = os.path.join(base_dir, name) + ".*"
                    candidates = glob.glob(full_path)
                    if not candidates:
                        candidates.append(os.path.join(base_dir, name + ".tex"))

                if not candidates:
                    continue

                target = os.path.abspath(candidates[0])

                try:
                    if target in cache:
                        preamble = cache[target]
                    else:
                        with open(target, encoding="utf-8", errors="ignore") as g:
                            nested = g.read()
                        if target in processed:
                            preamble = nested
                        else:
                            processed.add(target)
                            preamble = resolve_content(target, nested)
                        cache[target] = preamble

                    replaced = False
                    for c in ("input", "include", "subfile", "usepackage"):
                        token = f"\\{c}{{{name}}}"
                        if token in content:
                            content = content.replace(token, preamble)
                            replaced = True
                    if not replaced:
                        content = preamble + "\n" + content
                except Exception:
                    continue

        return content

    abs_file = os.path.abspath(file)
    with open(abs_file, "r+", encoding="utf-8", errors="ignore") as f:
        content = f.read()
        content = resolve_content(abs_file, content)
        f.seek(0)
        f.write(content)
        f.truncate()