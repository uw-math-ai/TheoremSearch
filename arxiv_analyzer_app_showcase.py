import os
import tarfile
import json
import re
import shutil
import arxiv
import google.generativeai as genai
from dotenv import load_dotenv
import time
from urllib.error import URLError
import argparse
import random

# --- 1. Configure the Google API Key and Model ---
load_dotenv()
# Make sure to set your GOOGLE_API_KEY in a .env file
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
model = genai.GenerativeModel('gemini-2.5-flash')
print("Google AI client configured successfully.")

# --- 2. Define arXiv Math Categories ---
ARXIV_MATH_CATEGORIES = [
    "math.AC", "math.AG", "math.AP", "math.AT", "math.CA", "math.CO",
    "math.CT", "math.CV", "math.DG", "math.DS", "math.FA", "math.GM",
    "math.GN", "math.GR", "math.GT", "math.HO", "math.IT", "math.KT",
    "math.LO", "math.MG", "math.MP", "math.NA", "math.NT", "math.OA",
    "math.OC", "math.PR", "math.QA", "math.RA", "math.RT", "math.SG",
    "math.SP", "math.ST"
]

# --- 3. Function to Call the Gemini Model ---
def call_gemini_for_global_context(full_text: str) -> str:
    """
    Calls the Gemini model once to find global context and requests a JSON output.
    """
    print("\n--- Calling Google Gemini API for global context extraction... ---")
    prompt = f"""You are a document extraction system. Your task is to analyze the following LaTeX source of a research paper and extract three types of global information:

1.  **Global Notations**: Extract any notations that are defined to be used throughout the paper.
2.  **Global Definitions**: Extract any foundational definitions that apply to the entire paper.
3.  **Global Assumptions**: Extract any explicit global assumptions or standing hypotheses.

Quote the findings directly from the text. If a category is empty, use an empty string. Your entire response must be a single, valid JSON object following this exact schema:
{{
    "global_notations": "<str>",
    "global_definitions": "<str>",
    "global_assumptions": "<str>"
}}

---
**Full Paper Text:**
{full_text}
---
**JSON Output:**
"""
    try:
        response = model.generate_content(prompt)
        clean_response = response.text.strip().replace("```json", "").replace("```", "")
        return clean_response
    except Exception as e:
        print(f"--- An error occurred with the API call: {e} ---")
        return "{}"

# --- 4. Helper Functions for Parsing ---
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

def extract_raw_theorems(main_file_path: str):
    """
    Uses regex to extract all theorem-like environments from the main .tex file.
    """
    if not main_file_path: return []
    theorem_environments = ["theorem", "lemma", "proposition", "corollary", "definition", "remark", "assumption"]
    pattern = re.compile(r"\\begin\{(" + "|".join(theorem_environments) + r")\*?\}\[?.*?\]?(.+?)\\end\{\1\*?\}", re.DOTALL)
    try:
        with open(main_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        matches = pattern.findall(content)
        return [{"type": match[0].strip(), "content": match[1].strip()} for match in matches]
    except Exception as e:
        print(f"Could not parse file with regex: {e}")
        return []

# --- 5. Main Workflow ---
if __name__ == "__main__":
    
    parser = argparse.ArgumentParser(description="Collect random papers systematically from each arXiv math category.")
    parser.add_argument(
        "--papers_per_category", 
        type=int, 
        default=1,
        help="The number of new papers to download for each category."
    )
    args = parser.parse_args()

    PARSED_DIR = "./app_papers"
    SOURCE_DIR_BASE = "./downloaded_sources"
    
    os.makedirs(PARSED_DIR, exist_ok=True)
    os.makedirs(SOURCE_DIR_BASE, exist_ok=True)

    client = arxiv.Client()
    modern_id_pattern = re.compile(r'^\d{4}\.\d{4,}') # Regex for modern IDs like YYMM.NNNN+
    
    for category in ARXIV_MATH_CATEGORIES:
        print(f"\n{'='*60}")
        print(f"Searching for random modern papers in category: {category}")
        print(f"{'='*60}")
        
        try:
            # Get a pool of recent papers to sample from
            search = arxiv.Search(
                query=f"cat:{category}",
                max_results=100, # Get a pool of 100 recent papers
                sort_by=arxiv.SortCriterion.SubmittedDate
            )
            
            all_results = list(client.results(search))
            
            # Filter for papers with a modern ID format
            modern_papers = [
                r for r in all_results if modern_id_pattern.match(r.get_short_id())
            ]

            if not modern_papers:
                print(f"Warning: No modern-format papers found in the top 100 recent for {category}. Skipping.")
                continue
            
            # Shuffle the list to randomize the selection
            random.shuffle(modern_papers)

            papers_found_for_category = 0
            for result in modern_papers:
                if papers_found_for_category >= args.papers_per_category:
                    break

                paper_id = result.get_short_id().replace('/', '_')
                output_filename = os.path.join(PARSED_DIR, f"{paper_id}_analysis.json")

                if os.path.exists(output_filename):
                    print(f"Paper {paper_id} already exists. Checking next random paper.")
                    continue

                print(f"\n--- Processing new random paper: {result.title} ({paper_id}) ---")
                source_dir = os.path.join(SOURCE_DIR_BASE, f"{paper_id}_source")
                if os.path.exists(source_dir): shutil.rmtree(source_dir)
                os.makedirs(source_dir)

                try:
                    time.sleep(3) # Be nice to the API
                    tar_path = result.download_source(dirpath=source_dir, filename=f"{paper_id}.tar.gz")
                    with tarfile.open(tar_path, "r:gz") as tar:
                        tar.extractall(path=source_dir)
                
                except (URLError, tarfile.TarError, Exception) as e:
                    print(f"ERROR: Could not download or extract source. Skipping. Details: {e}")
                    shutil.rmtree(source_dir)
                    continue

                main_tex_file = find_main_tex_file(source_dir)
                
                if main_tex_file:
                    theorems_list = extract_raw_theorems(main_tex_file)
                    print(f"Found {len(theorems_list)} theorem-like environments.")
                    
                    with open(main_tex_file, 'r', encoding='utf-8', errors='ignore') as f:
                        full_paper_text = f.read()

                    json_response_str = call_gemini_for_global_context(full_paper_text)
                    
                    try:
                        global_context = json.loads(json_response_str)
                    except json.JSONDecodeError:
                        print("Error: Failed to parse JSON response from the model.")
                        global_context = {}

                    final_output = {
                        "source": "arXiv", "title": result.title,
                        "authors": [author.name for author in result.authors],
                        "url": result.entry_id, "year": result.updated.year, "citations": 0,
                        "journal_published": bool(result.journal_ref),
                        "primary_math_tag": result.primary_category,
                        "global_notations": global_context.get("global_notations", ""),
                        "global_definitions": global_context.get("global_definitions", ""),
                        "global_assumptions": global_context.get("global_assumptions", ""),
                        "theorems": theorems_list
                    }

                    with open(output_filename, 'w', encoding='utf-8') as f:
                        json.dump(final_output, f, indent=4)
                    print(f"Analysis saved to {output_filename} ✅")
                    papers_found_for_category += 1
                    
                    shutil.rmtree(source_dir)
                else:
                    print("Could not find a main .tex file. Skipping.")
                    shutil.rmtree(source_dir)
        
        except Exception as e:
            print(f"An unexpected error occurred while processing category {category}: {e}")
            continue

    print(f"\n{'='*60}\nFinished collecting papers for all categories.\n{'='*60}")