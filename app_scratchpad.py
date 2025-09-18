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
    Loads theorem data from the specified JSON files and prepares it for embedding.
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
        except FileNotFoundError:
            st.warning(f"Warning: The data file '{file_path}' was not found.")
        except json.JSONDecodeError:
            st.warning(f"Warning: Could not decode JSON from {file_path}.")

    return all_theorems_data

# --- 3. The Search and Display Function ---
def clean_latex_for_display(text: str) -> str:
    """
    Cleans raw LaTeX for display in Streamlit, with direct \FPlint replacement.
    """
    # 1. Force‐replace any \FPlint or \FPInt with \dashint
    text = text.replace(r'\FPlint', r'\dashint')
    text = text.replace(r'\FPInt',  r'\dashint')

    # 2. Strip out metadata and macro definitions
    text = re.sub(
        r'\\(DeclareMathOperator|newcommand|renewcommand)\*?\{.*?\}\{.*?\}',
        '',
        text,
        flags=re.DOTALL
    )
    text = re.sub(
        r'\\(label|ref|cite|eqref|footnote|footnotetext|def|let|alert)\{.*?\}',
        '',
        text
    )

    # 3. Handle block environments (\begin{…}\end{…}, \[ … \])
    def wrap_env(match):
        content = match.group(2).strip()
        return f"$$\n\\begin{{aligned}}\n{content}\n\\end{{aligned}}\n$$"

    text = re.sub(
        r'\\begin\{(equation|align|gather|multline|flalign|dmath)\*?\}(.*?)\\end\{\1\*?\}',
        wrap_env,
        text,
        flags=re.DOTALL
    )
    text = re.sub(r'\\\[(.*?)\\\]', r'$$\n\1\n$$', text, flags=re.DOTALL)

    # 4. Wrap any stray line containing '&' as an aligned block
    lines = text.split('\n')
    processed = []
    for line in lines:
        if '&' in line:
            processed.append(f"$$\n\\begin{{aligned}}\n{line}\n\\end{{aligned}}\n$$")
        else:
            processed.append(line)
    text = '\n'.join(processed)

    # 5. Convert inline math \(...\) → $...$
    text = re.sub(r'\\\((.*?)\\\)', r'$\1$', text)

    # 6. Final cleanup: strip leftover \begin/\end and normalize newlines
    text = re.sub(r'\\begin\{.*?\}', '', text, flags=re.DOTALL)
    text = re.sub(r'\\end\{.*?\}', '', text, flags=re.DOTALL)
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()

def search_theorems(query, model, theorems_data, embeddings_db):
    """
    Finds and displays the top 5 most similar theorems.
    """
    if not query:
        st.info("Please enter a search query.")
        return

    query_emb      = model.encode(query, convert_to_tensor=True)
    cosine_scores  = util.cos_sim(query_emb, embeddings_db)[0]
    top_indices    = np.argsort(-cosine_scores.cpu())[:5]

    st.subheader("Top 5 Most Similar Theorems")

    for i, idx in enumerate(top_indices):
        idx        = idx.item()
        similarity = cosine_scores[idx].item()
        info       = theorems_data[idx]

        expander_title = (
            f"**Result {i+1} | Similarity: {similarity:.4f} | "
            f"Type: {info['type'].capitalize()}**"
        )
        with st.expander(expander_title):
            st.markdown(f"**Paper:** *{info['paper_title']}*")
            st.markdown(f"**Source:** [{info['paper_url']}]({info['paper_url']})")

            if info["global_context"]:
                cleaned_ctx    = clean_latex_for_display(info["global_context"])
                blockquote_ctx = "> " + cleaned_ctx.replace("\n", "\n> ")
                st.markdown(blockquote_ctx)
                st.write("")

            cleaned_content = clean_latex_for_display(info['content'])
            st.markdown(cleaned_content)

# --- Main App Interface ---
st.set_page_config(page_title="Theorem Search Demo", layout="wide")

st.title("📚 Semantic Theorem Search")
st.write("This demo uses a specialized mathematical language model to find theorems semantically similar to your query.")

model = load_model()

PARSED_DIR = "./parsed_papers"
if os.path.exists(PARSED_DIR):
    paper_files = [
        os.path.join(PARSED_DIR, f)
        for f in os.listdir(PARSED_DIR)
        if f.endswith('.json')
    ]
else:
    paper_files = []
    st.error(f"Error: The directory '{PARSED_DIR}' not found. Add your parsed JSON files.")

if not paper_files:
    st.warning("No parsed paper files (.json) found in the 'parsed_papers' directory.")
else:
    theorems_data = load_and_prepare_data(paper_files)

    if model and theorems_data:
        with st.spinner("Embedding theorems from all papers..."):
            corpus_texts      = [item['text_to_embed'] for item in theorems_data]
            corpus_embeddings = model.encode(corpus_texts, convert_to_tensor=True)
        st.success(f"Embedded {len(theorems_data)} theorems from {len(paper_files)} papers. Ready to search!")

        user_query = st.text_input("Enter your query:", "The Jones polynomial is a link invariant")
        search_theorems(user_query, model, theorems_data, corpus_embeddings)
    else:
        st.error("Could not load the model or data. The application cannot proceed.")