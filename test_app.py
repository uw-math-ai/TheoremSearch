import streamlit as st
import json
import numpy as np
from sentence_transformers import SentenceTransformer, util
import os # <--- ADDED this missing import

# --- 1. Load the Embedding Model ---
# Use a try-except block to show a user-friendly message during the initial download.
@st.cache_resource
def load_model():
    """
    Loads the specialized math embedding model from Hugging Face.
    Using @st.cache_resource ensures this is only done once per session.
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
    Using @st.cache_data ensures this is only done once, speeding up reruns.
    """
    all_theorems_data = []
    for file_path in paper_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                global_assumptions = data.get("global_assumptions", "")
                # Extract the base ID for the URL, handling both 'math_...' and '...' formats
                arxiv_id = os.path.basename(file_path).replace('_analysis.json', '').replace('_', '/')
                
                for theorem in data.get("theorems", []):
                    all_theorems_data.append({
                        "paper_url": f"https://arxiv.org/abs/{arxiv_id}",
                        "type": theorem["type"],
                        "content": theorem["content"],
                        "text_to_embed": f"Global Assumptions: {global_assumptions}\n\n{theorem['type'].capitalize()}: {theorem['content']}"
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

    # Embed the user's query
    query_embedding = model.encode(query, convert_to_tensor=True)

    # Calculate cosine similarities
    cosine_scores = util.cos_sim(query_embedding, embeddings_db)[0]
    
    # Get the indices of the top 5 scores
    top_results_indices = np.argsort(-cosine_scores.cpu())[:5]

    st.subheader("Top 5 Most Similar Theorems")
    
    if len(top_results_indices) == 0:
        st.write("No results found.")
        return

    for idx in top_results_indices:
        idx = idx.item()
        similarity = cosine_scores[idx].item()
        theorem_info = theorems_data[idx]

        # Display results in a formatted way
        st.markdown(f"**Similarity:** `{similarity:.4f}`")
        st.markdown(f"**Paper:** [{theorem_info['paper_url']}]({theorem_info['paper_url']})")
        st.markdown(f"**Type:** {theorem_info['type'].capitalize()}")
        
        # Using st.latex to correctly render mathematical notation
        st.latex(theorem_info['content'])
        st.markdown("---")

# --- Main App Interface ---

# Set up the page title and layout
st.set_page_config(page_title="Theorem Search Demo", layout="wide")
st.title("📚 Semantic Theorem Search")
st.write("This demo uses a specialized mathematical language model to find theorems semantically similar to your query.")

# Load the model and data
model = load_model()
paper_files = ["1402.0290_analysis.json", "2507.22091_analysis.json"]
theorems_data = load_and_prepare_data(paper_files)

if model and theorems_data:
    # Embed the entire corpus of theorems. This will only run once.
    with st.spinner("Embedding theorems from all papers... This may take a moment on first run."):
        corpus_texts = [item['text_to_embed'] for item in theorems_data]
        corpus_embeddings = model.encode(corpus_texts, convert_to_tensor=True)
    st.success(f"Successfully embedded {len(theorems_data)} theorems. Ready to search!")

    # Get user input
    user_query = st.text_input("Enter your query:", "The Jones polynomial is a link invariant")
    
    # Perform the search when the user enters a query
    search_theorems(user_query, model, theorems_data, corpus_embeddings)
else:
    st.error("Could not load the model or data. Please ensure the JSON files exist and required libraries are installed.")