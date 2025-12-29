import requests
import os
import tarfile
import json
import re
from io import BytesIO
import google.generativeai as genai
from dotenv import load_dotenv
import shutil # <--- ADDED for directory cleanup

# --- 1. Configure the Google API Key and Model ---
load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
# Using the latest available model as discussed
model = genai.GenerativeModel('gemini-2.5-flash')
print("Google AI client configured successfully.")

# --- 2. The Function to Call the Gemini Model ---
def call_gemini_for_global_assumptions(full_text: str) -> str:
    """
    Calls the Gemini model once to find the paper's global assumptions.
    """
    print("\n--- Calling Google Gemini API to find global assumptions... ---")

    prompt = f"""You are a document extraction system. Your task is to analyze the following LaTeX source of a research paper and perform one task only:

1.  **Extract Global Assumptions**: Find and list any statements that are explicitly defined as global assumptions, foundational frameworks, or standing hypotheses for the entire paper.
    - Quote these assumptions directly from the text.
    - Do not interpret, summarize, or add any information not present in the text.
    - If no such global assumptions are explicitly stated, respond with "No global assumptions were explicitly stated in the document."


Your entire response must consist only of the list of assumptions or the "no assumptions" message. Do not add any introductory or concluding phrases.

---
**Full Paper Text:**
{full_text}
---
**Global Assumptions:**
"""
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"--- An error occurred with the API call: {e} ---")
        return f"Error: API call failed. Details: {e}"

# --- 3. Helper Functions ---
def download_and_extract_source(arxiv_id: str, download_path: str = "paper_source"):
    # Using the /e-print/ endpoint as requested
    source_url = f"https://arxiv.org/e-print/{arxiv_id}"
    print(f"Downloading source for {arxiv_id} from {source_url}...")
    try:
        response = requests.get(source_url, stream=True)
        response.raise_for_status()
        with BytesIO(response.content) as file_stream:
            with tarfile.open(fileobj=file_stream, mode="r:gz") as tar:
                if not os.path.exists(download_path):
                    os.makedirs(download_path)
                tar.extractall(path=download_path)
        print(f"Successfully extracted files to '{download_path}'")
        return download_path
    except Exception as e:
        print(f"An error occurred during download/extraction: {e}")
        return None

def find_main_tex_file(source_dir: str):
    for root, _, files in os.walk(source_dir):
        for file in files:
            if file.endswith(".tex"):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        if r"\documentclass" in f.read():
                            print(f"Found main .tex file: {file_path}")
                            return file_path
                except Exception:
                    continue
    return None

def extract_raw_theorems(main_file_path: str):
    if not main_file_path: return []
    theorem_environments = ["theorem", "lemma", "proposition", "corollary", "definition", "remark", "assumption"]
    pattern = re.compile(r"\\begin\{(" + "|".join(theorem_environments) + r")\*?\}\[?.*?\]?(.+?)\\end\{\1\*?\}", re.DOTALL)
    try:
        with open(main_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        matches = pattern.findall(content)
        return [{"type": match[0].strip(), "content": match[1].strip()} for match in matches]
    except Exception as e:
        print(f"Could not parse file with regex: {e}")
        return []

# --- 4. Main Workflow ---
if __name__ == "__main__":

    # FIXED: Added cleanup step for fresh analysis
    if os.path.exists("paper_source"):
        print("--- Removing old paper source files... ---")
        shutil.rmtree("paper_source")

    arxiv_url = "https://arxiv.org/abs/2509.03506"

    # FIXED: Robust way to get the ID from any arXiv URL
    arxiv_id = arxiv_url.split('/abs/')[-1]

    source_directory = download_and_extract_source(arxiv_id)

    if source_directory:
        main_tex_file = find_main_tex_file(source_directory)

        if main_tex_file:
            theorems_list = extract_raw_theorems(main_tex_file)
            print(f"\nFound {len(theorems_list)} theorem-like environments with regex.")

            with open(main_tex_file, 'r', encoding='utf-8') as f:
                full_paper_text = f.read()

            global_assumptions = call_gemini_for_global_assumptions(full_paper_text)

            final_output = {
                "global_assumptions": global_assumptions,
                "theorems": theorems_list
            }

            # FIXED: Sanitize the arxiv_id to create a valid filename
            safe_arxiv_id = arxiv_id.replace('/', '_')
            output_filename = f"{safe_arxiv_id}_analysis.json"

            with open(output_filename, 'w', encoding='utf-8') as f:
                json.dump(final_output, f, indent=4)
            print(f"\nAnalysis complete! Results saved to {output_filename} ✅")