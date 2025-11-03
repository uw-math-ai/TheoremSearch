"""
Helpers to search or extract from .tex files.
"""

from tarfile import TarFile
from .latex_parse import _scanner

def extract_main_tex_file_content(tar: TarFile) -> str:
    for member in tar.getmembers():
        extracted = tar.extractfile(member)

        if extracted:
            content = extracted.read().decode("utf-8")

            if r"\documentclass" in content:
                return content
            
    return None

def collect_imports(import_appends: str, tar: TarFile, content: str, pattern: str):
    """
    collects any tex that is imported into the main document, can include user-macros, sections, etc.
    """
    paper_imports = _scanner(pattern, content)

    if paper_imports:
        for item in paper_imports:
            if item.group("filepath")[-4:] not in [".tex", ".sty", ".cls"]:
                matches = [m for m in tar.getnames() if m.startswith(item.group("filepath") + ".")]
                
                if matches:
                    tar_member_path = matches[0]
                else:
                    continue

            else:
                tar_member_path = item.group("filepath")
            
            try:
                extracted = tar.extractfile(tar_member_path)
                if extracted is None:
                    continue
                preamble = extracted.read().decode("utf-8", errors="ignore")
            except Exception:
                continue

            import_appends = preamble + import_appends
        return import_appends
    else:
        return import_appends
        
  