import streamlit as st
import json
import numpy as np
from sentence_transformers import SentenceTransformer, util
import os
import boto3
import psycopg2
from psycopg2.extensions import connection
from dotenv import load_dotenv
from latex_clean import clean_latex_for_display

# Config
load_dotenv()

def get_rds_connection() -> connection:
    region = os.getenv("AWS_REGION")
    secret_arn = os.getenv("RDS_SECRET_ARN")
    host = os.getenv("RDS_HOST")
    dbname = os.getenv("RDS_DB_NAME")

    sm = boto3.client("secretsmanager", region_name=region)
    secret_value = sm.get_secret_value(SecretId=secret_arn)
    secret_dict = json.loads(secret_value["SecretString"])

    conn = psycopg2.connect(
        host=host or secret_dict.get("host"),
        port=int(secret_dict.get("port", 5432)),
        dbname=dbname or secret_dict.get("dbname"),
        user=secret_dict["username"],
        password=secret_dict["password"],
        sslmode="require",
    )
    return conn

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

# Load the Embedding Model
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


# Load Data from RDS
@st.cache_data
def load_papers_from_rds():
    """
    Loads theorem data from the RDS database and prepares it for embedding.
    Returns a list of theorem dictionaries with all necessary fields.
    """
    try:
        conn = get_rds_connection()
        cur = conn.cursor()

        # Fetch all papers with their theorems and embeddings
        cur.execute("""
            SELECT 
                tm.paper_id,
                tm.title,
                tm.authors,
                tm.link,
                tm.last_updated,
                tm.summary,
                tm.journal_ref,
                tm.primary_category,
                tm.categories,
                tm.global_notations,
                tm.global_definitions,
                tm.global_assumptions,
                te.theorem_name,
                te.theorem_slogan,
                te.theorem_body,
                te.embedding
            FROM theorem_metadata tm
            JOIN theorem_embedding te ON tm.paper_id = te.paper_id
            ORDER BY tm.paper_id, te.theorem_name;
        """)

        rows = cur.fetchall()
        cur.close()
        conn.close()

        all_theorems_data = []
        for row in rows:
            (paper_id, title, authors, link, last_updated, summary,
             journal_ref, primary_category, categories,
             global_notations, global_definitions, global_assumptions,
             theorem_name, theorem_slogan, theorem_body, embedding) = row

            # Build global context
            global_context_parts = []
            if global_notations:
                global_context_parts.append(f"**Global Notations:**\n{global_notations}")
            if global_definitions:
                global_context_parts.append(f"**Global Definitions:**\n{global_definitions}")
            if global_assumptions:
                global_context_parts.append(f"**Global Assumptions:**\n{global_assumptions}")

            global_context = "\n\n".join(global_context_parts)

            # Convert embedding to a numpy float array
            if isinstance(embedding, str):
                embedding = json.loads(embedding)
            if isinstance(embedding, list):
                embedding = np.array(embedding, dtype=np.float32)
            elif isinstance(embedding, np.ndarray):
                embedding = embedding.astype(np.float32)

            all_theorems_data.append({
                "paper_id": paper_id,
                "authors": authors,
                "paper_title": title,
                "paper_url": link,
                "year": last_updated.year,
                "primary_category": primary_category,
                "theorem_name": theorem_name,
                "theorem_slogan": theorem_slogan,
                "theorem_body": theorem_body,
                "global_context": global_context,
                "stored_embedding": embedding
            })

        return all_theorems_data

    except Exception as e:
        st.error(f"Error loading data from RDS: {e}")
        return []


# --- 3. The Search Function ---
def search_theorems(query, model, theorems_data, embeddings_db):
    """
    Takes a user query and finds the top 10 most similar theorems.
    """
    if not query:
        st.info("Please enter a search query.")
        return

    query_embedding = model.encode(query, convert_to_tensor=True)
    cosine_scores = util.cos_sim(query_embedding, embeddings_db)[0]
    top_results_indices = np.argsort(-cosine_scores.cpu())[:10]

    st.subheader("Top 5 Most Similar Theorems")

    if len(top_results_indices) == 0:
        st.write("No results found.")
        return

    for i, idx in enumerate(top_results_indices):
        idx = idx.item()
        similarity = cosine_scores[idx].item()
        theorem_info = theorems_data[idx]

        expander_title = f"**Result {i+1} | Similarity: {similarity:.4f}**"
        if theorem_info.get("theorem_name"):
            expander_title += f" | {theorem_info['theorem_name']}"

        with st.expander(expander_title):
            st.markdown(f"**Paper:** {theorem_info.get('paper_title', 'Unknown')}")
            st.markdown(f"**Authors:** {', '.join(theorem_info['authors']) if theorem_info['authors'] else 'N/A'}")
            st.markdown(f"**Source:** [{theorem_info['paper_url']}]({theorem_info['paper_url']})")
            st.markdown(
                f"**Math Tag:** `{theorem_info['primary_category']}` | **Year:** {theorem_info.get('year', 'N/A')}")
            st.markdown("---")

            if theorem_info.get("theorem_slogan"):
                st.markdown(f"**Slogan:** {theorem_info['theorem_slogan']}")
                st.write("")

            if theorem_info["global_context"]:
                cleaned_ctx = clean_latex_for_display(theorem_info["global_context"])
                st.markdown(f"> {cleaned_ctx.replace('\n', '\n> ')}")
                st.write("")

            cleaned_content = clean_latex_for_display(theorem_info['theorem_body'])
            st.markdown(f"**Theorem Body:**")
            st.markdown(cleaned_content)

# --- Main App Interface ---
st.set_page_config(page_title="Theorem Search Demo", layout="wide")
st.title("📚 Semantic Theorem Search")
st.write("This demo uses a specialized mathematical language model to find theorems semantically similar to your query.")
st.markdown("*Note: Linking to a specific page within an arXiv PDF is not directly possible.*",
            help="arXiv links redirect to the paper's abstract, not a specific page in the PDF.")

model = load_model()
theorems_data = load_papers_from_rds()

if model and theorems_data:
    with st.spinner("Preparing embeddings from database..."):
        corpus_embeddings = np.array([item['stored_embedding'] for item in theorems_data])

    st.success(f"Successfully loaded {len(theorems_data)} theorems from arXiv. Ready to search!")

    user_query = st.text_input("Enter your query:", "")

    if st.button("Search") or user_query:
        search_theorems(user_query, model, theorems_data, corpus_embeddings)
else:
    st.error("Could not load the model or data from RDS. Please check your RDS database connection and credentials.")