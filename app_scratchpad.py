import streamlit as st
import json
import numpy as np
from sentence_transformers import SentenceTransformer, util
import os
import re

# --- 1. Load the Embedding Model ---
@st.cache_resource
def load_model():
    """
    Loads the specialized math embedding model from Hugging Face.
    """
    try:
        model = SentenceTransformer('math-similarity/Bert-MLM_arXiv-MP-class_zbMath')
        return model
    except Exception as e:
        st.error(f"Error loading the embedding model: {e}")
        return None

# --- 2. Load and Prepare the Data ---
@st.cache_data
def load_and_prepare_data(paper_files):
    """
    Loads theorem data from JSON files and prepares it for embedding.
    """
    all_theorems_data = []
    for file_path in paper_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                # Load all global context fields
                global_notations = data.get("global_notations", "")
                global_definitions = data.get("global_definitions", "")
                global_assumptions = data.get("global_assumptions", "")
                
                # Combine them into a single string for display and embedding
                global_context_parts = []
                if global_notations:
                    global_context_parts.append(f"**Global Notations:**\n{global_notations}")
                if global_definitions:
                    global_context_parts.append(f"**Global Definitions:**\n{global_definitions}")
                if global_assumptions:
                    global_context_parts.append(f"**Global Assumptions:**\n{global_assumptions}")
                
                global_context = "\n\n".join(global_context_parts)

                arxiv_id = os.path.basename(file_path).replace('_analysis.json', '').replace('_', '/')
                
                for theorem in data.get("theorems", []):
                    all_theorems_data.append({
                        "paper_url": f"https://arxiv.org/abs/{arxiv_id}",
                        "type": theorem["type"],
                        "content": theorem["content"],
                        "global_context": global_context, # Store for display
                        "text_to_embed": f"{global_context}\n\n**{theorem['type'].capitalize()}:**\n{theorem['content']}"
                    })
        except FileNotFoundError:
            st.warning(f"Warning: The data file {file_path} was not found.")
        except json.JSONDecodeError:
            st.warning(f"Warning: Could not decode JSON from {file_path}.")
            
    return all_theorems_data

# --- 3. The Search Function ---
def search_theorems(query, model, theorems_data, embeddings_db):
    """
    Takes a user query and finds the top 5 most similar theorems.
    """
    if not query:
        st.info("Please enter a search query.")
        return

    query_embedding = model.encode(query, convert_to_tensor=True)
    cosine_scores = util.cos_sim(query_embedding, embeddings_db)[0]
    top_results_indices = np.argsort(-cosine_scores.cpu())[:5]

    st.subheader("Top 5 Most Similar Theorems")
    
    if len(top_results_indices) == 0:
        st.write("No results found.")
        return

    for i, idx in enumerate(top_results_indices):
        idx = idx.item()
        similarity = cosine_scores[idx].item()
        theorem_info = theorems_data[idx]

        # Use an expander for each result to keep the main view clean
        expander_title = f"**Result {i+1} | Similarity: {similarity:.4f} | Type: {theorem_info['type'].capitalize()}**"
        with st.expander(expander_title):
            st.markdown(f"**Source:** [{theorem_info['paper_url']}]({theorem_info['paper_url']})")

            # Display global context in a more readable blockquote
            if theorem_info["global_context"]:
                blockquote_context = "> " + theorem_info["global_context"].replace("\n", "\n> ")
                st.markdown(blockquote_context)
                st.write("") 

            # FIXED: More aggressive cleaning of the LaTeX string
            content = theorem_info['content']
            
            # Remove labels, citations, and other disruptive commands
            cleaned_content = re.sub(r'\\(label|cite|eqref)\{.*?\}', '', content)
            
            # Remove common environment wrappers like \begin{...} and \end{...}
            cleaned_content = re.sub(r'\\begin\{.*?\}', '', cleaned_content)
            cleaned_content = re.sub(r'\\end\{.*?\}', '', cleaned_content)
            
            # Remove extra formatting like newlines and tabs
            cleaned_content = cleaned_content.replace('\n', ' ').replace('\t', ' ').strip()
            
            # Use st.markdown() to render the cleaned, mixed text and LaTeX
            st.markdown(cleaned_content)


# --- Main App Interface ---
st.set_page_config(page_title="Theorem Search Demo", layout="wide")
st.title("📚 Semantic Theorem Search")
st.write("This demo uses a specialized mathematical language model to find theorems semantically similar to your query.")

model = load_model()
paper_files = ["1402.0290_analysis.json", "2507.22091_analysis.json", "2509.03506_analysis.json"]
theorems_data = load_and_prepare_data(paper_files)

if model and theorems_data:
    with st.spinner("Embedding theorems from all papers... This may take a moment on first run."):
        corpus_texts = [item['text_to_embed'] for item in theorems_data]
        corpus_embeddings = model.encode(corpus_texts, convert_to_tensor=True)
    st.success(f"Successfully embedded {len(theorems_data)} theorems. Ready to search!")

    user_query = st.text_input("Enter your query:", "The Jones polynomial is a link invariant")
    
    search_theorems(user_query, model, theorems_data, corpus_embeddings)
else:
    st.error("Could not load the model or data. Please ensure the JSON files exist and required libraries are installed.")