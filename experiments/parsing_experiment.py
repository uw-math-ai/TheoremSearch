# the goal is to obtain the theorems given the url of the arxiv paper
# steps
# 1. download the tex file of the paper
# 2. unzip the tex file
# 3. given the names of the files find the main one (maybe call to qwen, try to make some progress,
#    use the model itself not embeddings, use something like qwen 0.6b using the coding snippet on huggingface,
#    https://huggingface.co/Qwen/Qwen3-0.6B)
# 4. parse the main file to extract theorems (**Challenge**)
import requests
import os
import re
import tarfile
from io import BytesIO

# Part 1 and 2: download and unzip the tex file
def download_and_extract_source(arxiv_id: str, download_path: str = "paper_source") -> str:
    # 1. Construct the download URL
    source_url = f"https://arxiv.org/e-print/{arxiv_id}"
    print(f"Downloading source for {arxiv_id} from {source_url}...")
    
    # 2. Download the file
    response = requests.get(source_url, stream=True)
    
    # 3. Handle the file in memory
    with BytesIO() as file_stream:
        file_stream.write(response.content)
        file_stream.seek(0)
        
        # 4. Unzip the file
        with tarfile.open(fileobj=file_stream, mode="r:gz") as tar:
            if not os.path.exists(download_path):
                os.makedirs(download_path)
            tar.extractall(path=download_path)
            
    print(f"Successfully extracted files to '{download_path}'")
    return download_path

# Part 3: find the main .tex file
def find_main_tex_file(source_dir: str) -> str:
    # 1. Walk through all files in the directory
    for root, _, files in os.walk(source_dir):
        # 2. Check each file
        for file in files:
            if file.endswith(".tex"):
                file_path = os.path.join(root, file)
                # 3. Read the file's content
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # 4. The crucial check
                    if r"\documentclass" in content:
                        print(f"Found main .tex file: {file_path}")
                        return file_path
    return None

# Part 4: extract theorems from the main .tex file 
def extract_theorems(main_file_path: str) -> list:
    # 1. Define theorem-like words
    theorem_environments = [
        "theorem", "lemma", "proposition", 
        "corollary", "definition", "remark", 
        "example", "proof", "assumption"
    ]
    
    # 2. Build a Regular Expression (Regex)
    pattern = re.compile(
        r"\\begin\{(" + "|".join(theorem_environments) + r")\*?\}\[?.*?\]?(.+?)\\end\{\1\*?\}",
        re.DOTALL
    )
    
    # 3. Read the file and find all matches
    with open(main_file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    matches = pattern.findall(content)
    
    # 4. Format the results
    extracted_theorems = []
    for match in matches:
        env_name = match[0].strip()
        env_content = match[1].strip()
        extracted_theorems.append({"type": env_name, "content": env_content})
            
    return extracted_theorems

# Run
if __name__ == "__main__":
    arxiv_url = "https://arxiv.org/abs/2507.22091"
    arxiv_id = arxiv_url.split('/')[-1]
    
    source_directory = download_and_extract_source(arxiv_id)
    if source_directory:
        main_tex_file = find_main_tex_file(source_directory)
        if main_tex_file:
            theorems = extract_theorems(main_tex_file)
            
            if theorems:
                print(f"\n--- Found {len(theorems)} Theorem-Like Environments ---")
                
                # --- NEW: Code to save the results ---
                output_filename = f"{arxiv_id}_theorems.txt"
                with open(output_filename, 'w', encoding='utf-8') as f:
                    print(f"Saving results to {output_filename}...")
                    for i, theorem in enumerate(theorems, 1):
                        f.write(f"{i}. Type: {theorem['type']}\n")
                        f.write("-" * 20 + "\n")
                        f.write(theorem['content'] + "\n")
                        f.write("-" * 20 + "\n\n")
                print("Save complete! ✅")
                # ----------------------------------------
                
                # You can still print them to the screen as well if you like
                for i, theorem in enumerate(theorems, 1):
                    print(f"\n{i}. Type: {theorem['type']}")
                    print("-" * 20)
                    print(theorem['content'])
                    print("-" * 20)
            else:
                print("No theorem-like environments were found.")