import os
import tarfile
import json
import re
import shutil
import arxiv 
import google.generativeai as genai
from dotenv import load_dotenv

# --- 1. Configure the Google API Key and Model ---
load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
model = genai.GenerativeModel('gemini-2.5-flash')
print("Google AI client configured successfully.")

# --- 2. Function to Call the Gemini Model ---
def call_gemini_for_global_context(full_text: str) -> str:
    """
    Calls the Gemini model once to find global notations, definitions, and assumptions,
    and requests the output in a specific JSON format.
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
        # Clean up the response to ensure it's a valid JSON string
        clean_response = response.text.strip().replace("```json", "").replace("```", "")
        return clean_response
    except Exception as e:
        print(f"--- An error occurred with the API call: {e} ---")
        return "{}" # Return an empty JSON object on error

# --- 3. Helper Functions for Parsing ---
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

# --- 4. Main Workflow ---
if __name__ == "__main__":
    
    # --- Define your search query for the arXiv API ---
    SEARCH_QUERY = "ti:\"Finite time blowup for an averaged\" AND au:Tao"
    MAX_PAPERS_TO_PROCESS = 1
    
    print(f"Searching arXiv for query: '{SEARCH_QUERY}'...")
    search = arxiv.Search(
        query=SEARCH_QUERY,
        max_results=MAX_PAPERS_TO_PROCESS,
        sort_by=arxiv.SortCriterion.SubmittedDate
    )

    client = arxiv.Client()

    for result in client.results(search):
        print(f"\n{'='*50}")
        print(f"Processing Paper: {result.title}")
        print(f"arXiv ID: {result.get_short_id()}")
        print(f"{'='*50}\n")

        paper_id = result.get_short_id().replace('/', '_')
        source_dir = f"./{paper_id}_source"
        output_filename = f"{paper_id}_analysis.json"
        
        if os.path.exists(source_dir):
            shutil.rmtree(source_dir)
        os.makedirs(source_dir)

        try:
            print(f"Downloading source for {paper_id}...")
            tar_path = result.download_source(dirpath=source_dir, filename=f"{paper_id}.tar.gz")
            with tarfile.open(tar_path, "r:gz") as tar:
                tar.extractall(path=source_dir)
            print(f"Successfully extracted source to '{source_dir}'")
        
        except (arxiv.DownloadException, tarfile.TarError) as e:
            print(f"ERROR: Could not download or extract source for {paper_id}. Skipping. Details: {e}")
            continue

        main_tex_file = find_main_tex_file(source_dir)
        
        if main_tex_file:
            theorems_list = extract_raw_theorems(main_tex_file)
            print(f"\nFound {len(theorems_list)} theorem-like environments with regex.")
            
            with open(main_tex_file, 'r', encoding='utf-8', errors='ignore') as f:
                full_paper_text = f.read()

            # Call the LLM to get the structured JSON response
            json_response_str = call_gemini_for_global_context(full_paper_text)
            
            # Parse the JSON string into a Python dictionary
            try:
                global_context = json.loads(json_response_str)
            except json.JSONDecodeError:
                print("Error: Failed to parse JSON response from the model. Saving raw response.")
                global_context = {"raw_error_response": json_response_str}

            # Prepare the final output dictionary
            final_output = {
                "title": result.title,
                "authors": [author.name for author in result.authors],
                "url": result.entry_id,
                "global_notations": global_context.get("global_notations", ""),
                "global_definitions": global_context.get("global_definitions", ""),
                "global_assumptions": global_context.get("global_assumptions", ""),
                "theorems": theorems_list
            }

            with open(output_filename, 'w', encoding='utf-8') as f:
                json.dump(final_output, f, indent=4)
            print(f"\nAnalysis complete! Results saved to {output_filename} ✅")