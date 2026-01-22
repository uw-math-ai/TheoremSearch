import streamlit as st
from sentence_transformers import SentenceTransformer

from latex_clean import clean_latex_for_display
from db import (fetch_results, load_theorem_count, load_tags,
                load_authors, load_sources, insert_feedback, load_source_caps)
from utils import (metadata_sources, serialize_filters, active_filters, SOURCE_FILTERS,
                   parse_paper_filter)
import time

# Config
@st.cache_resource
def load_model():
    try:
        model = SentenceTransformer('Qwen/Qwen3-Embedding-0.6B')
        return model
    except Exception as e:
        st.error(f"Error loading the embedding model: {e}")
        return None

# --- Search and Display ---
def search_and_display(query: str, model, filters: dict):
    if not filters:
        st.warning("Please select at least one source to search over.")
        return

    serialized_filters = serialize_filters(filters)

    citation_weight = float(filters['citation_weight'])
    top_k = int(filters["top_k"])

    # Encode query
    t0 = time.time()
    query_vec = model.encode(query or "", normalize_embeddings=True)
    embed_time = time.time() - t0

    where = []
    params = []

    meta_sources = metadata_sources(filters["sources"], source_caps)

    if meta_sources:
        # Filter by source(s)
        where.append("source = ANY(%s)")
        params.append(meta_sources)

        # Filter by author(s)
        if filters["authors"]:
            where.append("authors && %s")
            params.append(filters["authors"])

        # Filter by primary arXiv category
        if filters["tags"]:
            where.append("primary_category = ANY(%s)")
            params.append(filters["tags"])

        # Filter by year range
        if filters["year_range"]:
            y0, y1 = filters["year_range"]
            where.append("year BETWEEN %s AND %s")
            params.extend([y0, y1])

        # Filter by published status
        if filters["journal_status"] != "All":
            where.append("journal_published = %s")
            params.append(filters["journal_status"] == "Journal Article")

        # Filter by citation range
        low, high = filters["citation_range"]
        if filters["include_unknown_citations"]:
            where.append("(citations BETWEEN %s AND %s OR citations IS NULL)")
        else:
            where.append("citations BETWEEN %s AND %s")
        params.extend([low, high])

        # Filter by arXiv id in link or title substring(s)
        pf = filters.get("paper_filter", {"ids": set(), "titles": set()})
        id_patterns = [f"{i}%" for i in pf["ids"]]
        title_patterns = [f"%{t}%" for t in pf["titles"]]
        clauses = []
        params_block = []
        if id_patterns:
            clauses.append("paper_id LIKE ANY(%s)")
            params_block.append(id_patterns)
        if title_patterns:
            clauses.append("title ILIKE ANY(%s)")
            params_block.append(title_patterns)
        if clauses:
            where.append(f"({' OR '.join(clauses)})")
            params.extend(params_block)

    where_sql = "WHERE " + " AND ".join(where)

    # Fetch results from RDS
    t0 = time.time()
    results = fetch_results(citation_weight, query_vec, params, where_sql, top_k)
    st.toast(f"**Embed time:** {embed_time} &nbsp; **SQL time:** {time.time() - t0}", icon="⏱")

    # --- Display results ---
    if not results:
        st.warning("No results found for the current filters.")
        return

    for i, r in enumerate(results):
        with st.expander(
            f"***{r['title']}* &nbsp; | &nbsp; {r['theorem_name']} &nbsp; | &nbsp; [Link]({r['link']})**",
            expanded=True
        ):
            theorem_col, feedback_col = st.columns([15, 1])
            with theorem_col:
                st.markdown(f"{r['theorem_slogan']}\n")
                st.markdown(clean_latex_for_display(r["theorem_body"]))
            with feedback_col:
                feedback = st.feedback(
                    "thumbs",
                    key=f"feedback_{r['slogan_id']}"
                )
                if feedback is not None:
                    submitted_key = f"submitted_{r['slogan_id']}"
                    if not st.session_state.get(submitted_key, False):
                        payload = {
                            "feedback": 1 if feedback == 1 else -1,
                            "query": query,
                            "url": r["link"],
                            "theorem_name": r["theorem_name"],
                            "authors": ", ".join(r["authors"]) if r["authors"] else None,
                            **serialized_filters,
                        }
                        insert_feedback(payload)
                        st.session_state[submitted_key] = True
                        st.toast("Thank you for the feedback!")

# --- Main App Interface ---
st.set_page_config(page_title="Theorem Search Demo", layout="wide")
st.title("Math Theorem Search")
st.write("This tool finds mathematical theorems that are semantically similar to your query.")

theorem_count = load_theorem_count()
authors_per_source = load_authors()
tags_per_source = load_tags()
all_sources = load_sources()
source_caps = load_source_caps()
model = load_model()

if model:
    if 'show_success' not in st.session_state:
        st.session_state['show_success'] = False
    if not st.session_state['show_success']:
        st.toast(f"Successfully loaded {theorem_count} theorems from arXiv and the Stacks Project. Ready to search!")
        st.session_state['show_success'] = True
    # --- Sidebar filters ---
    st.logo(image="../images/math-ai-logo.jpg", size="large", link="https://sites.math.washington.edu/ai/")
    with st.sidebar:
        st.header("Search Filters")

        selected_sources = st.multiselect(
            "Filter by Source:",
            all_sources,
            default=[],
            help="Select one or more sources to search from."
        )

        top_k_results = 50

        if selected_sources:
            with st.expander("Advanced Filters"):
                caps = active_filters(selected_sources)

                if caps["types"]:
                    selected_types = st.multiselect(
                        "Filter by Result Type:",
                        ["theorem", "lemma", "proposition", "corollary"]
                    )
                else:
                    selected_types = []

                if caps["authors"]:
                    allowed_authors = sorted({
                        a
                        for s in selected_sources
                        if SOURCE_FILTERS[s]["authors"]
                        for a in authors_per_source.get(s, [])
                    })
                    selected_authors = st.multiselect(
                        "Filter by Author(s):",
                        allowed_authors
                    )
                else:
                    selected_authors = []

                if caps["tags"]:
                    allowed_tags = sorted({
                        t
                        for s in selected_sources
                        if SOURCE_FILTERS[s]["tags"]
                        for t in tags_per_source.get(s, [])
                    })
                    selected_tags = st.multiselect(
                        "Filter by Tag / Category:",
                        allowed_tags
                    )
                else:
                    selected_tags = []

                if caps["paper_filter"]:
                    paper_filter = st.text_input(
                        "Filter by Paper",
                        placeholder="2401.12345, Finite Hilbert stability"
                    )
                else:
                    paper_filter = ""

                if caps["year"]:
                    year_range = st.slider("Year", 1991, 2026, (1991, 2026))
                else:
                    year_range = None

                if caps["journal"]:
                    journal_status = st.radio(
                        "Publication Status",
                        ["All", "Journal Article", "Preprint"],
                        horizontal=True
                    )
                else:
                    journal_status = "All"

                if caps["citations"]:
                    citation_range = st.slider("Citations", 0, 1502, (0, 1502), step=10)
                    citation_weight = st.slider("Citation Weight", 0.0, 1.0, 0.0)
                    include_unknown_citations = st.checkbox("Include unknown citations", True)
                else:
                    citation_range = (0, 10 ** 9)
                    citation_weight = 0.0
                    include_unknown_citations = True
            filters = {
                "authors": selected_authors,
                "types": [t.lower() for t in selected_types],
                "tags": selected_tags,
                "sources": selected_sources,
                "paper_filter": parse_paper_filter(paper_filter),
                "year_range": year_range,
                "journal_status": journal_status,
                "citation_range": citation_range,
                "citation_weight": citation_weight,
                "include_unknown_citations": include_unknown_citations,
                "top_k": top_k_results,
            }
        else:
            filters = {}
    user_query = st.text_input("Enter your query:", "", placeholder="Example: The Jones polynomial is link invariant")
    if st.button("Search") or user_query:
        with st.spinner("Fetching theorems..."):
            search_and_display(user_query, model, filters)
else:
    st.error("Could not load the model or data from RDS. Please try again later.")