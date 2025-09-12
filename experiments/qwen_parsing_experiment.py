import requests
import os
import tarfile
import json
import re
from io import BytesIO
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

# --- 1. Load Model and Set Safety Limit ---
MODEL_NAME = "Qwen/Qwen2-1.5B-Instruct"
# Set a safe token limit. 4096 is a common context size for models of this type.
MAX_TOKENS = 4096 

print(f"Loading model: {MODEL_NAME}...")
try:
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        torch_dtype="auto",
        device_map="auto"
    )
    print(f"Model loaded successfully onto device: {model.device}")
except Exception as e:
    print(f"Error loading model: {e}")
    exit()

# --- 2. The REAL Function to Call the Model (with error handling) ---
def call_qwen_model(prompt: str) -> str:
    print("--- Calling LLM for analysis... ---")
    
    # Truncate the prompt if it's too long for the model
    inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=MAX_TOKENS).to(model.device)
    
    try:
        outputs = model.generate(**inputs, max_new_tokens=512)
        response_text = tokenizer.decode(outputs[0], skip_special_tokens=True)
        
        response_start_marker = "### Required Assumptions and Definitions:"
        start_index = response_text.rfind(response_start_marker)
        if start_index != -1:
            return response_text[start_index + len(response_start_marker):].strip()
        else:
            return response_text
    except torch.cuda.OutOfMemoryError:
        print("--- CAUGHT CUDA OutOfMemoryError: Skipping this theorem. ---")
        return "Error: Could not process this theorem due to its size."

# --- 3. Helper Functions (Unchanged) ---
def download_and_extract_source(arxiv_id: str, download_path: str = "paper_source"):
    source_url = f"https://arxiv.org/e-print/{arxiv_id}"
    print(f"Downloading source for {arxiv_id}...")
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
    theorem_environments = ["theorem", "lemma", "proposition", "corollary", "definition", "remark", "example", "proof", "assumption"]
    pattern = re.compile(r"(\\begin\{(" + "|".join(theorem_environments) + r")\*?\}\[?.*?\]?(.+?)\\end\{\2\*?\})", re.DOTALL)
    try:
        with open(main_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        matches = pattern.finditer(content)
        return [{"full_match": m.group(1), "type": m.group(2).strip(), "content": m.group(3).strip(), "start_pos": m.start(1)} for m in matches]
    except Exception as e:
        print(f"Could not parse file with regex: {e}")
        return []

# --- 4. Main Workflow ---
if __name__ == "__main__":
    arxiv_url = "https://arxiv.org/abs/1706.03762"
    arxiv_id = arxiv_url.split('/')[-1]
    
    source_directory = download_and_extract_source(arxiv_id)
    
    if source_directory:
        main_tex_file = find_main_tex_file(source_directory)
        
        if main_tex_file:
            raw_theorems = extract_raw_theorems(main_tex_file)
            print(f"\nFound {len(raw_theorems)} theorem-like environments with regex.")
            
            with open(main_tex_file, 'r', encoding='utf-8') as f:
                full_paper_text = f.read()

            enriched_theorems = []
            
            print("\n--- Starting LLM analysis for each theorem with adaptive context ---")
            for i, theorem in enumerate(raw_theorems):
                print(f"Analyzing theorem {i+1}/{len(raw_theorems)} (Type: {theorem['type']})...")
                
                CONTEXT_SIZE = 4000
                start_context = max(0, theorem['start_pos'] - CONTEXT_SIZE)
                end_context = theorem['start_pos'] + len(theorem['full_match']) + CONTEXT_SIZE
                context_window = full_paper_text[start_context:end_context]

                prompt = f"""You are an expert research assistant. Given a text window from a paper and a theorem from that window, identify the assumptions for that specific theorem based ONLY on the provided text.

---
### Text Window from Paper:

{context_window}
---
### Theorem to Analyze:

{theorem['content']}
---
### Required Assumptions and Definitions:
"""
                assumptions = call_qwen_model(prompt)
                
                enriched_theorems.append({
                    "type": theorem['type'],
                    "content": theorem['content'],
                    "assumptions": assumptions
                })

            output_filename = f"{arxiv_id}_theorems_with_assumptions.json"
            with open(output_filename, 'w', encoding='utf-8') as f:
                json.dump(enriched_theorems, f, indent=4)
            print(f"\nAnalysis complete! Results saved to {output_filename} ✅")