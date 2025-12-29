import streamlit as st
import re
import torch
import pickle
import os
from sentence_transformers import SentenceTransformer, util

# --- 1. Configuration and Data Loading ---

MODEL_NAME = 'math-similarity/Bert-MLM_arXiv-MP-class_zbMath'
EMBEDDING_LIBRARY_DIR = "./app_embeds" # Configured to load from your new directory

AVAILABLE_TAGS = {
    "arXiv": [
        "math.AC", "math.AG", "math.AP", "math.AT", "math.CA", "math.CO",
        "math.CT", "math.CV", "math.DG", "math.DS", "math.FA", "math.GM",
        "math.GN", "math.GR", "math.GT", "math.HO", "math.IT", "math.KT",
        "math.LO", "math.MG", "math.MP", "math.NA", "math.NT", "math.OA",
        "math.OC", "math.PR", "math.QA", "math.RA", "math.RT", "math.SG",
        "math.SP", "math.ST", "Statistics Theory"
    ],
    "Stacks Project": [
        "Sets", "Schemes", "Algebraic Stacks", "Étale Cohomology"
    ]
}

ALLOWED_TYPES = [
    "theorem", "lemma", "proposition", "corollary", "definition", "remark", "assumption"
]

@st.cache_resource
def load_model():
    """Loads the sentence transformer model from HuggingFace."""
    try:
        return SentenceTransformer(MODEL_NAME)
    except Exception as e:
        st.error(f"Error loading embedding model: {e}")
        return None

@st.cache_data
def load_embedding_library(directory):
    """Loads the pre-computed embeddings and theorem metadata from disk."""
    embeddings_path = os.path.join(directory, "corpus_embeddings.pt")
    data_path = os.path.join(directory, "theorems_data.pkl")

    if not os.path.exists(embeddings_path) or not os.path.exists(data_path):
        st.error(f"Error: Embedding library not found in '{directory}'.")
        st.info("Please run the `app_create_embeddings.py` script first to generate the necessary files.")
        return None, None

    try:
        embeddings = torch.load(embeddings_path, map_location=torch.device('cpu'))
        with open(data_path, 'rb') as f:
            theorems_data = pickle.load(f)
        return embeddings, theorems_data
    except Exception as e:
        st.error(f"Error loading files from the embedding library: {e}")
        return None, None

# --- 2. Cleaning and Display Logic ---
def clean_latex_for_display(text: str) -> str:
    """Cleans raw LaTeX for display in Streamlit."""
    text = text.replace(r'\FPlint', r'\dashint').replace(r'\FPInt',  r'\dashint')
    text = re.sub(r'\\(DeclareMathOperator|newcommand|renewcommand)\*?\{.*?\}\{.*?\}', '', text, flags=re.DOTALL)
    text = re.sub(r'\\(label|ref|cite|eqref|footnote|footnotetext|def|let|alert)\{.*?\}', '', text)
    def wrap_env(match):
        return f"$$\n\\begin{{aligned}}\n{match.group(2).strip()}\n\\end{{aligned}}\n$$"
    text = re.sub(r'\\begin\{(equation|align|gather|multline|flalign|dmath)\*?\}(.*?)\\end\{\1\*?\}', wrap_env, text, flags=re.DOTALL)
    text = re.sub(r'\\\[(.*?)\\\]', r'$$\n\1\n$$', text, flags=re.DOTALL)
    lines, processed = text.split('\n'), []
    for line in lines:
        processed.append(f"$$\n\\begin{{aligned}}\n{line}\n\\end{{aligned}}\n$$" if '&' in line else line)
    text = '\n'.join(processed)
    text = re.sub(r'\\\((.*?)\\\)', r'$\1$', text)
    text = re.sub(r'\\begin\{.*?\}|\\end\{.*?\}', '', text, flags=re.DOTALL)
    return re.sub(r'\n{3,}', '\n\n', text).strip()

# --- 3. Search and Display Logic ---
def search_and_display(query, model, theorems_data, embeddings_db, filters):
    """
    Performs semantic search, filters the results, and displays them.
    """
    if not query:
        st.info("Please enter a search query to begin.")
        return

    if not filters['sources']:
        st.warning("Please select at least one source from the sidebar to see results.")
        return

    # 1. Perform Semantic Search
    query_emb = model.encode(query, convert_to_tensor=True)
    cosine_scores = util.cos_sim(query_emb, embeddings_db)[0]

    # Get a larger pool of top results to filter through
    top_indices = torch.topk(cosine_scores, k=min(200, len(theorems_data)), sorted=True).indices

    # 2. Filter Results
    filtered_results = []
    for idx in top_indices:
        idx = idx.item()
        item = theorems_data[idx]

        # Apply all filters
        type_match = not filters['types'] or item['type'].lower() in filters['types']
        tag_match = not filters['tags'] or item['primary_math_tag'] in filters['tags']
        author_match = not filters['authors'] or any(author in item['authors'] for author in filters['authors'])
        source_match = item['source'] in filters['sources']
        citation_match = filters['citation_range'][0] <= item['citations'] <= filters['citation_range'][1]

        year_match = True
        if filters['year_range'] and item['source'] == 'arXiv':
            year_match = filters['year_range'][0] <= item.get('year', 0) <= filters['year_range'][1]

        journal_match = True
        if item['source'] == 'arXiv':
            if filters['journal_status'] == "Journal Article":
                journal_match = item.get('journal_published', False)
            elif filters['journal_status'] == "Preprint Only":
                journal_match = not item.get('journal_published', False)

        if all([type_match, tag_match, author_match, source_match, year_match, citation_match, journal_match]):
            filtered_results.append({
                "info": item,
                "similarity": cosine_scores[idx].item()
            })

        if len(filtered_results) >= filters['top_k']:
            break

    # 3. Display Filtered Results
    st.subheader(f"Found {len(filtered_results)} Matching Results")
    if not filtered_results:
        st.warning("No results found matching your query and filter criteria.")
        return

    for i, result in enumerate(filtered_results):
        info = result['info']
        expander_title = (
            f"**Result {i+1} | Similarity: {result['similarity']:.4f} | "
            f"Type: {info['type'].capitalize()}**"
        )
        with st.expander(expander_title):
            st.markdown(f"**Paper:** *{info['paper_title']}*")
            st.markdown(f"**Authors:** {', '.join(info['authors']) if info['authors'] else 'N/A'}")
            st.markdown(f"**Source:** {info['source']} ([Link]({info['paper_url']}))")
            st.markdown(f"**Math Tag:** `{info['primary_math_tag']}` | **Citations:** {info['citations']} | **Year:** {info.get('year', 'N/A')}")
            st.markdown("*Note: Linking to a specific page within an arXiv PDF is not directly possible.*", help="arXiv links go to the abstract page, not a specific page in the PDF.")
            st.markdown("---")

            if info["global_context"]:
                cleaned_ctx = clean_latex_for_display(info["global_context"])
                st.markdown(f"> {cleaned_ctx.replace('\n', '\n> ')}")
                st.write("")

            cleaned_content = clean_latex_for_display(info['content'])
            st.markdown(cleaned_content)

# --- Main App Interface ---
st.set_page_config(page_title="Semantic Theorem Search", layout="wide")

st.title("Semantic Theorem Search")
st.write("Find semantically similar theorems, definitions, and lemmas from a library of research papers.")

# Load model and pre-computed data
model = load_model()
corpus_embeddings, theorems_data = load_embedding_library(EMBEDDING_LIBRARY_DIR)

if model and theorems_data:
    st.success(f"Loaded embedding library with {len(theorems_data)} theorems. Ready to search!")

    # --- Sidebar for Filters ---
    with st.sidebar:
        st.header("Search Filters")

        all_sources_from_data = sorted(list(set(item['source'] for item in theorems_data)))
        selected_sources = st.multiselect(
            "Filter by Source(s):",
            all_sources_from_data,
            help="Select one or more sources to reveal more filters."
        )

        # Initialize filter variables
        selected_authors, selected_types, selected_tags = [], [], []
        year_range, journal_status = None, "All"
        citation_range = (0, 1000000)
        top_k_results = 5

        if selected_sources:
            st.write("---")
            selected_types = st.multiselect("Filter by Type:", ALLOWED_TYPES)
            
            all_authors = sorted(list(set(author for item in theorems_data for author in item.get('authors', []))))
            selected_authors = st.multiselect("Filter by Author(s):", all_authors)

            tags_to_display = sorted(list(set(tag for src in selected_sources for tag in AVAILABLE_TAGS.get(src, []))))
            selected_tags = st.multiselect("Filter by Math Tag/Category:", tags_to_display)

            if 'arXiv' in selected_sources:
                year_range = st.slider("Filter by Year (for arXiv):", 1991, 2025, (1991, 2025))
                journal_status = st.radio("Publication Status (for arXiv):", ["All", "Journal Article", "Preprint Only"], horizontal=True)

            citation_range = st.slider("Filter by Citations:", 0, 1000000, (0, 1000000))
            top_k_results = st.slider("Number of results to display:", 1, 20, 5)

    filters = {
        "authors": selected_authors, "types": [t.lower() for t in selected_types],
        "tags": selected_tags, "sources": selected_sources, "year_range": year_range,
        "journal_status": journal_status, "citation_range": citation_range, "top_k": top_k_results
    }

    user_query = st.text_input("Enter your query:", "")
    search_and_display(user_query, model, theorems_data, corpus_embeddings, filters)

else:
    st.error("Application could not start. Please check for errors in the console and ensure the embedding library exists.")