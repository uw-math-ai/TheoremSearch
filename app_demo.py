import streamlit as st
import json
import numpy as np
from sentence_transformers import SentenceTransformer, util
import os
import boto3
import psycopg2
from psycopg2.extensions import connection
import torch
import re
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
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

ARXIV_ID_RE = re.compile(
    r'(?:arxiv\.org/(?:abs|pdf)/)?((?:\d{4}\.\d{4,5}|[a-z\-]+/\d{7}))',
    re.IGNORECASE
)

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

            # Determine source from url
            link_str = link or ""
            if link_str.startswith("http://arxiv.org") or link_str.startswith("https://arxiv.org"):
                source = "arXiv"
            else:
                source = "Stacks Project"

            # Determine type from name
            def infer_type(name: str) -> str:
                if not name:
                    return "theorem"
                lower = name.lower()
                for t in ["theorem", "lemma", "proposition", "corollary", "definition", "remark", "assumption"]:
                    if t in lower:
                        return t
                return "theorem"

            inferred_type = infer_type(theorem_name or "")

            all_theorems_data.append({
                "paper_id": paper_id,
                "authors": authors,
                "paper_title": title,
                "paper_url": link,
                "year": last_updated.year,
                "primary_category": primary_category,
                "source": source,
                "type": inferred_type,
                "journal_published": bool(journal_ref),
                "citations": None,
                "theorem_name": theorem_name,
                "theorem_slogan": theorem_slogan,
                "theorem_body": theorem_body,
                "global_context": global_context,
                "stored_embedding": embedding,
            })

        return all_theorems_data

    except Exception as e:
        st.error(f"Error loading data from RDS: {e}")
        return []

@st.cache_data(ttl=60*60*24) # cache for 24 hours
def fetch_citations(paper_url: str, title: str) -> int | None:
    """
    Returns citation count if found, else None.
    Tries the following sources in order:
      1) OpenAlex by arXiv id
      2) Semantic Scholar by arXiv id
      3) Semantic Scholar by title
    """
    arx_id = None
    if paper_url:
        m = ARXIV_ID_RE.search(paper_url)
        if m:
            arx_id = m.group(1)
    # OpenAlex by arXiv id
    if arx_id:
        try:
            r = requests.get(f"https://api.openalex.org/works/arXiv:{arx_id}", timeout=10)
            if r.ok:
                data = r.json()
                c = data.get("cited_by_count")
                if isinstance(c, int):
                    return c
        except Exception:
            pass
    # Semantic Scholar by arXiv id
    if arx_id:
        try:
            r = requests.get(
                f"https://api.semanticscholar.org/graph/v1/paper/arXiv:{arx_id}",
                params={"fields": "citationCount"},
                timeout=10
            )
            if r.ok:
                j = r.json()
                c = j.get("citationCount")
                if isinstance(c, int):
                    return c
        except Exception:
            pass
    # Fallback: Semantic Scholar by title
    if title:
        try:
            r = requests.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params={"query": title, "limit": 1, "fields": "title,citationCount"},
                timeout=10
            )
            if r.ok:
                j = r.json()
                if j.get("data"):
                    c = j["data"][0].get("citationCount")
                    if isinstance(c, int):
                        return c
        except Exception:
            pass

    return None

def add_citations(candidates: list[dict], max_workers: int = 6) -> None:
    # Select targets with missing citations
    targets = [
        it for it in candidates
        if it.get("source") == "arXiv" and (it.get("citations") in (None, 0))
    ]
    if not targets:
        return

    with ThreadPoolExecutor(max_workers=max_workers) as exe:
        fut2item = {
            exe.submit(fetch_citations, it.get("paper_url"), it.get("paper_title")): it
            for it in targets
        }
        for fut in as_completed(fut2item):
            it = fut2item[fut]
            try:
                c = fut.result()
                if c is not None:
                    it["citations"] = c
            except Exception:
                pass

def extract_arxiv_id(s: str) -> str | None:
    """Return normalized arXiv ID if present in s (URL or raw), else None."""
    if not s:
        return None
    m = ARXIV_ID_RE.search(s.strip())
    return m.group(1) if m else None

def normalize_title(s: str) -> str:
    return (s or "").casefold().strip()

def parse_paper_filter_input(raw: str) -> dict:
    """
    Parse user input into two sets: arxiv_ids and title substrings.
    Multiple entries may be comma-separated.
    e.g. "2401.12345, Optimal Transport" -> {"ids":{"2401.12345"}, "titles":{"optimal transport"}}
    """
    ids, titles = set(), set()
    if not raw:
        return {"ids": ids, "titles": titles}
    for token in [t.strip() for t in raw.split(",") if t.strip()]:
        arx = extract_arxiv_id(token)
        if arx:
            ids.add(arx.lower())
        else:
            titles.add(normalize_title(token))
    return {"ids": ids, "titles": titles}

def item_matches_paper_filter(item: dict, paper_filter: dict) -> bool:
    """
    True if the item matches at least one requested arXiv ID or one title substring.
    If paper_filter is empty (both sets empty), always True.
    """
    ids = paper_filter.get("ids", set())
    titles = paper_filter.get("titles", set())
    if not ids and not titles:
        return True

    # Compare IDs (extract once from url)
    url = item.get("paper_url") or ""
    item_id = extract_arxiv_id(url)
    if item_id and item_id.lower() in ids:
        return True

    # Compare titles (substring, case-insensitive)
    t = normalize_title(item.get("paper_title"))
    if t and any(sub in t for sub in titles):
        return True

    return False

# --- Search and Display ---
def search_and_display_with_filters(query, model, theorems_data, embeddings_db, filters):
    if not filters['sources']:
        st.warning("Please select at least one source.")
        return

    if query:
        query_embedding = model.encode(query, convert_to_tensor=True)
        cosine_scores = util.cos_sim(query_embedding, embeddings_db)[0]
    else:
        cosine_scores = torch.zeros(len(theorems_data))

    low, high = filters['citation_range']

    # Get a larger pool to filter from
    top_k_pool = min(200, len(theorems_data))
    top_indices = torch.topk(cosine_scores, k=top_k_pool, sorted=True).indices
    top_indices = top_indices.tolist()

    paper_filter = filters.get("paper_filter", {"ids": set(), "titles": set()})
    matched_indices = []
    if paper_filter and (paper_filter.get("ids") or paper_filter.get("titles")):
        for i, it in enumerate(theorems_data):
            if item_matches_paper_filter(it, paper_filter):
                matched_indices.append(i)

    pool_indices = list(dict.fromkeys(top_indices + matched_indices))
    pool = [(i, theorems_data[i]) for i in pool_indices]

    # Fetch citations in parallel
    if ('arXiv' in filters['sources']):
        add_citations([it for _, it in pool])

    results = []

    # Filter results
    for idx, item in pool:
        type_match = (not filters['types']) or (item.get('type','').lower() in filters['types'])
        tag_match = (not filters['tags'])  or (item.get('primary_category') in filters['tags'])
        author_match = (not filters['authors']) or any(a in (item.get('authors') or []) for a in filters['authors'])
        source_match = item.get('source') in filters['sources']
        paper_match = item_matches_paper_filter(item, filters['paper_filter'])

        # Citations & year & journal only for arXiv
        citations = item.get('citations')
        log_cit = np.log1p(int(citations)) if citations is not None else 0.0
        if citations is None:
            if not filters['include_unknown_citations']:
                continue
            citation_match = True
        else:
            citation_match = (low <= int(citations) <= high)

        year_match = True
        if filters['year_range'] and item.get('source') == 'arXiv':
            y = item.get('year') or 0
            yr0, yr1 = filters['year_range']
            year_match = (yr0 <= y <= yr1)

        journal_match = True
        if item.get('source') == 'arXiv':
            status = filters['journal_status']
            jp = bool(item.get('journal_published'))
            if status == "Journal Article":
                journal_match = jp
            elif status == "Preprint Only":
                journal_match = not jp

        if all([type_match, tag_match, author_match, source_match, paper_match, citation_match, year_match, journal_match]):
            # Similarity = cosine_similary + citation_weight * log(citation_count)
            similarity = float(cosine_scores[idx].item()) + filters['citation_weight'] * log_cit
            results.append({"idx": idx, "info": item, "similarity": similarity})
            if len(results) >= filters['top_k']:
                break

    results.sort(key=lambda r: r["similarity"], reverse=True)
    results = results[:filters['top_k']]

    st.subheader(f"Found {len(results)} Matching Results")
    if not results:
        st.warning("No results found for the current filters.")
        return

    for i, r in enumerate(results):
        info = r["info"]
        expander_title = f"**Result {i+1} | Similarity: {r['similarity']:.4f} | Type: {info.get('type','').title()}**"
        with st.expander(expander_title, expanded=True):
            st.markdown(f"**Paper:** *{info.get('paper_title','Unknown')}*")
            st.markdown(f"**Authors:** {', '.join(info.get('authors') or []) or 'N/A'}")
            st.markdown(f"**Source:** {info.get('source')} ({info.get('paper_url')})")
            citations = info.get("citations")
            cit_str = "Unknown" if citations is None else str(citations)
            st.markdown(
                f"**Math Tag:** `{info.get('primary_category')}` | "
                f"**Citations:** {cit_str} | "
                f"**Year:** {info.get('year', 'N/A')}"
            )
            # Testing only
            if filters['citation_weight'] > 0:
                base = float(cosine_scores[r["idx"]].item())
                log_cit = np.log1p(int(citations)) if citations is not None else 0.0
                st.caption(
                    f"base_cosine={base:.4f}  |  log(citations)={log_cit:.4f}  |  weight={filters['citation_weight']:.2f}")
            st.markdown("---")

            if info.get("theorem_slogan"):
                st.markdown(f"**Slogan:** {info['theorem_slogan']}\n")

            if info.get("global_context"):
                cleaned_ctx = clean_latex_for_display(info["global_context"])
                st.markdown("> " + cleaned_ctx.replace("\n", "\n> ") )

            cleaned_content = clean_latex_for_display(info['theorem_body'])
            st.markdown(f"**{info['theorem_name'] or 'Theorem Body.'}**")
            st.markdown(cleaned_content)

            # Testing only
            st.markdown('**Paper ID (testing only)**')
            st.markdown(info['paper_id'])

# --- Main App Interface ---
st.set_page_config(page_title="Theorem Search Demo", layout="wide")
st.title("📚 Semantic Theorem Search")
st.write("This demo uses a specialized mathematical language model to find theorems semantically similar to your query.")

model = load_model()
theorems_data = load_papers_from_rds()

if model and theorems_data:
    with st.spinner("Preparing embeddings from database..."):
        corpus_embeddings = np.array([item['stored_embedding'] for item in theorems_data])

    st.success(f"Successfully loaded {len(theorems_data)} theorems from arXiv and the Stacks Project. Ready to search!")

    # --- Sidebar filters ---
    with st.sidebar:
        st.header("Search Filters")

        all_sources = ['arXiv', 'Stacks Project']
        selected_sources = st.multiselect(
            "Filter by Source(s):",
            all_sources,
            default=all_sources[:1] if all_sources else [],
            help="Select one or more sources to reveal more filters."
        )

        selected_authors, selected_types, selected_tags = [], [], []
        year_range, journal_status = None, "All"
        citation_range = (0, 1000)
        citation_weight = 0.0
        include_unknown_citations = True
        top_k_results = 5

        if selected_sources:
            st.write("---")
            selected_types = st.multiselect("Filter by Type:", ALLOWED_TYPES)
            all_authors = sorted(list(set(a for it in theorems_data for a in (it.get('authors') or []))))
            selected_authors = st.multiselect("Filter by Author(s):", all_authors)

            # Tags come from the union of categories per selected source
            from collections import defaultdict
            tags_per_source = defaultdict(set)
            for it in theorems_data:
                tags_per_source[it['source']].add(it.get('primary_category'))
            union_tags = sorted({t for s in selected_sources for t in tags_per_source.get(s, set()) if t})
            selected_tags = st.multiselect("Filter by Math Tag/Category:", union_tags)
            paper_filter_raw = st.text_input("Filter by Paper",
                                             value="",
                                             placeholder="e.g., 2401.12345, Finite Hilbert stability",
                                             help="Filter by title substring or arXiv ID/URL. Use commas for multiple.")
            if 'arXiv' in selected_sources:
                year_range = st.slider("Filter by Year:", 1991, 2025, (1991, 2025))
                journal_status = st.radio("Publication Status:", ["All", "Journal Article", "Preprint Only"], horizontal=True)
                citation_range = st.slider("Filter by Citations:", 0, 1000, (0, 1000))
                citation_weight = st.slider("Citation Weight:", 0.0, 1.0, 0.0, step=0.01)
                include_unknown_citations = st.checkbox(
                    "Include entries with unknown citation counts",
                    value=True,
                    help="If unchecked, results with unknown citation counts are excluded."
                )
            top_k_results = st.slider("Number of Results to Display:", 1, 20, 5)

    filters = {
        "authors": selected_authors,
        "types": [t.lower() for t in selected_types],
        "tags": selected_tags,
        "sources": selected_sources,
        "paper_filter": parse_paper_filter_input(paper_filter_raw),
        "year_range": year_range,
        "journal_status": journal_status,
        "citation_range": citation_range,
        "citation_weight": citation_weight,
        "include_unknown_citations": include_unknown_citations,
        "top_k": top_k_results,
    }

    user_query = st.text_input("Enter your query:", "")
    if st.button("Search") or user_query:
        search_and_display_with_filters(user_query, model, theorems_data, corpus_embeddings, filters)
else:
    st.error("Could not load the model or data from RDS. Please check your RDS database connection and credentials.")