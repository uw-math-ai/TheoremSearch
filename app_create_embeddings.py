import json
import os
import torch
from sentence_transformers import SentenceTransformer
import pickle

# --- Configuration ---
MODEL_NAME = 'math-similarity/Bert-MLM_arXiv-MP-class_zbMath'
PARSED_PAPERS_DIR = "./app_papers"  # Input directory from your parser
OUTPUT_DIR = "./app_embeds"      # New output directory for the final library

def create_embedding_library():
    """
    Loads parsed paper data from the app_papers directory, generates embeddings for
    all theorems, and saves the final library files to the app_embeds directory.
    """
    print("🚀 Starting the embedding library creation process...")

    # 1. Load the Embedding Model
    print(f"Loading sentence transformer model: '{MODEL_NAME}'...")
    try:
        model = SentenceTransformer(MODEL_NAME)
    except Exception as e:
        print(f"❌ Error loading model: {e}")
        return

    # 2. Find and Load Parsed Paper Data
    if not os.path.exists(PARSED_PAPERS_DIR):
        print(f"❌ Error: The directory '{PARSED_PAPERS_DIR}' was not found.")
        print("   Please run the 'arxiv_analyzer_app_showcase.py' script first to generate paper data.")
        return

    json_files = [os.path.join(PARSED_PAPERS_DIR, f) for f in os.listdir(PARSED_PAPERS_DIR) if f.endswith('.json')]
    if not json_files:
        print(f"❌ No parsed JSON files found in '{PARSED_PAPERS_DIR}'.")
        return

    print(f"Found {len(json_files)} parsed paper(s). Loading and preparing data for embedding...")
    all_theorems_data = []
    
    # 3. Process each parsed paper file
    for file_path in json_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

                # Construct the global context string for this paper
                global_context = "\n\n".join(filter(None, [
                    f"**Global Notations:**\n{data.get('global_notations', '')}",
                    f"**Global Definitions:**\n{data.get('global_definitions', '')}",
                    f"**Global Assumptions:**\n{data.get('global_assumptions', '')}"
                ]))

                # Process each theorem within the paper
                for theorem in data.get("theorems", []):
                    # Append a dictionary with all metadata required by the Streamlit app
                    all_theorems_data.append({
                        "paper_title":      data.get("title", "N/A"),
                        "paper_url":        data.get("url", ""),
                        "authors":          data.get("authors", []),
                        "citations":        data.get("citations", 0),
                        "primary_math_tag": data.get("primary_math_tag", "N/A"),
                        "year":             data.get("year"),
                        "source":           data.get("source"),
                        "journal_published": data.get("journal_published"),
                        "type":             theorem["type"],
                        "content":          theorem["content"],
                        "global_context":   global_context,
                        "text_to_embed":    f"{global_context}\n\n**{theorem['type'].capitalize()}:**\n{theorem['content']}"
                    })
        except Exception as e:
            print(f"⚠️ Warning: Could not process file {file_path}. Error: {e}")

    if not all_theorems_data:
        print("❌ No theorems were extracted from the JSON files. Aborting.")
        return

    # 4. Generate Embeddings for the entire corpus
    print(f"Embedding {len(all_theorems_data)} total theorems. This may take a while...")
    corpus_texts = [item['text_to_embed'] for item in all_theorems_data]
    corpus_embeddings = model.encode(corpus_texts, convert_to_tensor=True, show_progress_bar=True)

    # 5. Save Embeddings and Metadata to Disk
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    embeddings_path = os.path.join(OUTPUT_DIR, "corpus_embeddings.pt")
    data_path = os.path.join(OUTPUT_DIR, "theorems_data.pkl")

    print(f"Saving embeddings tensor to '{embeddings_path}'...")
    torch.save(corpus_embeddings, embeddings_path)

    print(f"Saving theorem metadata to '{data_path}'...")
    with open(data_path, 'wb') as f:
        pickle.dump(all_theorems_data, f)

    print("\n✅ Embedding library created successfully!")
    print(f"   - {len(all_theorems_data)} theorems embedded.")
    print(f"   - Files saved in the '{OUTPUT_DIR}' directory.")

if __name__ == "__main__":
    create_embedding_library()