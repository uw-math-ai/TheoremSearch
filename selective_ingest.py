import os
import requests
import re
import json
import sys
import importlib.util

# --- 1. UNIVERSAL FILE LOCATOR ---
def find_parser():
    current_path = os.path.abspath(os.path.dirname(__file__))
    candidates = [
        os.path.join(current_path, "latex_parse.py"),
        os.path.join(current_path, "parsed_papers_to_vector_rds", "stacks_parsing", "latex_parse.py"),
        os.path.join(current_path, "stacks_parsing", "latex_parse.py"),
        os.path.join(current_path, "..", "stacks_parsing", "latex_parse.py")
    ]
    for path in candidates:
        if os.path.exists(path): return path
    return None

parser_file_path = find_parser()

if not parser_file_path:
    print("\n[!] CRITICAL ERROR: Could not find 'latex_parse.py'.")
    print("    Please ensure it exists inside 'parsed_papers_to_vector_rds/stacks_parsing'.")
    sys.exit(1)

# --- 2. LOAD THE PARSER ---
parser_dir = os.path.dirname(parser_file_path)
if parser_dir not in sys.path:
    sys.path.append(parser_dir)

try:
    spec = importlib.util.spec_from_file_location("latex_parse_mod", parser_file_path)
    latex_parse = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(latex_parse)
    extract = latex_parse.extract
    print(f"[+] Successfully loaded parser from: {parser_file_path}")
except Exception as e:
    print(f"[!] Import Error: {e}")
    sys.exit(1)


# --- 3. THE INGESTOR CLASS ---
class SelectiveIngestor:
    def __init__(self):
        # Determine root relative to the parser to keep structure clean
        root_dir = os.path.dirname(os.path.dirname(parser_dir))
        if "MathCopilot" not in root_dir:
            root_dir = os.path.dirname(os.path.abspath(__file__))
            
        self.base_output_dir = os.path.join(root_dir, "data", "sources") 
        self.owner = ""
        self.repo = ""

    def get_user_input(self):
        print("\n=== MathCopilot Selective Ingestor (.tex -> JSON) ===")
        url = input("Enter GitHub Repository Link: ").strip()
        
        if "xeqi/kerodon" in url:
            print("\n[!] WARNING: Wrong repo detected. Use 'https://github.com/stacks/stacks-project'.")
            if input("    Continue? (y/n): ").lower() != 'y': sys.exit()

        clean_url = url.replace("https://github.com/", "").replace(".git", "")
        self.owner, self.repo = clean_url.split("/")[:2]
        
        self.repo_dir = os.path.join(self.base_output_dir, f"{self.owner}_{self.repo}")
        if not os.path.exists(self.repo_dir):
            os.makedirs(self.repo_dir)

        print("\n(Optional) GitHub Token (Press Enter to skip).")
        self.token = input("Token: ").strip()

    def get_headers(self):
        return {"Authorization": f"token {self.token}"} if self.token else {}

    def find_tex_files(self):
        print(f"[*] Scanning {self.owner}/{self.repo}...")
        api_base = f"https://api.github.com/repos/{self.owner}/{self.repo}"
        
        r = requests.get(api_base, headers=self.get_headers())
        if r.status_code != 200:
            print(f"[-] Failed to connect. Status: {r.status_code}")
            return []
        
        default_branch = r.json().get("default_branch", "main")
        tree_url = f"{api_base}/git/trees/{default_branch}?recursive=1"
        r = requests.get(tree_url, headers=self.get_headers())
        
        if r.status_code != 200:
            print("[-] Failed to retrieve file tree.")
            return []

        files = r.json().get("tree", [])
        return [f for f in files if f['path'].endswith('.tex')]

    def normalize_latex(self, content):
        # Fix shorthand environments
        replacements = {
            r'\\begin\{thm\}': r'\\begin{theorem}', r'\\end\{thm\}': r'\\end{theorem}',
            r'\\begin\{lem\}': r'\\begin{lemma}', r'\\end\{lem\}': r'\\end{lemma}',
            r'\\begin\{defn\}': r'\\begin{definition}', r'\\end\{defn\}': r'\\end{definition}',
            r'\\begin\{prop\}': r'\\begin{proposition}', r'\\end\{prop\}': r'\\end{proposition}',
            r'\\begin\{cor\}': r'\\begin{corollary}', r'\\end\{cor\}': r'\\end{corollary}',
            r'\\begin\{rem\}': r'\\begin{remark}', r'\\end\{rem\}': r'\\end{remark}',
            r'\\begin\{ex\}': r'\\begin{example}', r'\\end\{ex\}': r'\\end{example}',
            r'\\begin\{thm\*\}': r'\\begin{theorem}', r'\\end\{thm\*\}': r'\\end{theorem}',
        }
        for old, new in replacements.items():
            content = re.sub(old, new, content)
        return content

    def process_content(self, content, original_path):
        clean_content = self.normalize_latex(content)
        
        # Inject Fake Document Wrapper so parser works
        dummy_wrapper = r"""
\documentclass{article}
\usepackage{amsmath, amssymb}
\newtheorem{theorem}{Theorem}[section]
\newtheorem{lemma}[theorem]{Lemma}
\newtheorem{proposition}[theorem]{Proposition}
\newtheorem{corollary}[theorem]{Corollary}
\newtheorem{definition}[theorem]{Definition}
\newtheorem{remark}[theorem]{Remark}
\newtheorem{example}[theorem]{Example}
\begin{document}
\section{Imported Content}
""" + clean_content + r"""
\end{document}
"""
        
        safe_filename = original_path.replace("/", "_")
        temp_tex_path = os.path.join(self.repo_dir, safe_filename)
        
        # 1. Create Temp File
        with open(temp_tex_path, 'w', encoding='utf-8') as f:
            f.write(dummy_wrapper)
        
        raw_theorems = []
        try:
            # 2. Run Parser
            raw_theorems = extract(temp_tex_path)
        except Exception as e:
            print(f"   [-] Parser error on {safe_filename}: {e}")
        
        # 3. CLEANUP: Delete the .tex file immediately!
        if os.path.exists(temp_tex_path):
            os.remove(temp_tex_path)

        if not raw_theorems:
            return

        # 4. Save JSON Only
        theorems_json = []
        for item in raw_theorems:
            theorems_json.append({
                "theorem_name": item[0],
                "body": item[1],
                "label": item[2],
                "type": "theorem" 
            })

        json_path = temp_tex_path.replace(".tex", ".json")
        output_data = {
            "source_repo": f"https://github.com/{self.owner}/{self.repo}",
            "original_path": original_path,
            "theorems": theorems_json
        }

        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2)
            print(f"   [+] Saved {len(theorems_json)} items -> {os.path.basename(json_path)}")

    def download_and_process(self, file_list):
        count = 0
        print(f"[+] Found {len(file_list)} files. Processing...")
        
        for item in file_list:
            path = item['path']
            raw_url = f"https://raw.githubusercontent.com/{self.owner}/{self.repo}/HEAD/{path}"
            
            try:
                r = requests.get(raw_url)
                if r.status_code == 200:
                    self.process_content(r.text, path)
                    count += 1
                else:
                    print(f"[-] Download failed for {path}")
            except Exception as e:
                print(f"[-] Error: {e}")
        
        print(f"\n[=] Done. Saved {count} parsed JSON files to {self.repo_dir}")

if __name__ == "__main__":
    ingestor = SelectiveIngestor()
    ingestor.get_user_input()
    files = ingestor.find_tex_files()
    if files:
        ingestor.download_and_process(files)