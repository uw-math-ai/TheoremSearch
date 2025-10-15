import json
from sentence_transformers import SentenceTransformer
import os
import torch

def _load_and_prepare_data(paper_files):
    """
    Loads theorem data from the specified JSON files and prepares it for embedding.
    * Directly taken from app_scratchpad.py. Needs updating to capture all metadata.
    """
    all_theorems_data = []
    for file_path in paper_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

                global_notations   = data.get("global_notations", "")
                global_definitions = data.get("global_definitions", "")
                global_assumptions = data.get("global_assumptions", "")

                global_context_parts = []
                if global_notations:
                    global_context_parts.append(f"**Global Notations:**\n{global_notations}")
                if global_definitions:
                    global_context_parts.append(f"**Global Definitions:**\n{global_definitions}")
                if global_assumptions:
                    global_context_parts.append(f"**Global Assumptions:**\n{global_assumptions}")

                global_context = "\n\n".join(global_context_parts)
                paper_url     = data.get("url", "")
                paper_title   = data.get("title", "N/A")

                for theorem in data.get("theorems", []):
                    all_theorems_data.append({
                        "paper_title":    paper_title,
                        "paper_url":      paper_url,
                        "type":           theorem["type"],
                        "content":        theorem["content"],
                        "global_context": global_context,
                        "text_to_embed":  f"{global_context}\n\n**{theorem['type'].capitalize()}:**\n{theorem['content']}"
                    })
        except Exception:
            print("An error occurred.")

    return all_theorems_data

def _get_embedder():
    return SentenceTransformer("math-similarity/Bert-MLM_arXiv-MP-class_zbMath")

def create_parsed_papers_metadata_and_embeddings(parsed_papers_dir: str = "parsed_papers"):
    parsed_papers = [
        os.path.join(parsed_papers_dir, f)
        for f in os.listdir(parsed_papers_dir)
        if f.endswith('.json')
    ]

    theorems_data = _load_and_prepare_data(parsed_papers)

    embedder = _get_embedder()

    all_embeddings_tensor = embedder.encode([item['text_to_embed'] for item in theorems_data], convert_to_tensor=True)
    all_embeddings = all_embeddings_tensor.detach().cpu().tolist()

    for item, embedding in zip(theorems_data, all_embeddings):
        item["embedding"] = embedding

    return theorems_data