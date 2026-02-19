import html
import os
import re
import streamlit as st
import streamlit.components.v1 as components
from latex_clean import clean_latex_for_display
from db import (
    fetch_results,
    load_theorem_count,
    load_tags,
    load_authors,
    load_sources,
    insert_feedback,
    load_source_caps,
    insert_query,
    cached_embed
)
from utils import (
    metadata_sources,
    serialize_filters,
    active_filters,
    SOURCE_FILTERS,
    parse_paper_filter)
import time

GA_MEASUREMENT_ID = os.getenv("GA_MEASUREMENT_ID", "G-XKM7PWE7EN")
if not re.fullmatch(r"G-[A-Za-z0-9]{10}", GA_MEASUREMENT_ID or ""):
    GA_MEASUREMENT_ID = "G-XKM7PWE7EN"
SAFE_GA_MEASUREMENT_ID = html.escape(GA_MEASUREMENT_ID, quote=True)

# Interface for searching and displaying results
def search_and_display(query: str, filters: dict):
    if not filters:
        st.warning("Select at least one source to search over.")
        return

    serialized_filters = serialize_filters(filters)

    citation_weight = float(filters['citation_weight'])
    top_k = int(filters["top_k"])

    # Encode query
    t0 = time.time()
    query_vec = cached_embed(query)
    embed_time = time.time() - t0
    t0 = time.time()

    where_clauses = []
    where_params = {}

    selected_sources = filters["sources"]
    meta_sources = metadata_sources(selected_sources, source_caps)

    # Types filter (all sources support types)
    if filters["types"]:
        where_clauses.append("theorem_type = ANY(%(types)s)")
        where_params["types"] = filters["types"]

    if meta_sources:
        # Authors
        if filters["authors"]:
            where_clauses.append("authors && %(authors)s")
            where_params["authors"] = filters["authors"]

        # Primary category
        if filters["tags"]:
            where_clauses.append("primary_category = ANY(%(tags)s)")
            where_params["tags"] = filters["tags"]

        # Year
        if filters["year_range"]:
            y0, y1 = filters["year_range"]
            where_clauses.append("year BETWEEN %(year_min)s AND %(year_max)s")
            where_params["year_min"] = y0
            where_params["year_max"] = y1

        # Journal status
        if filters["journal_status"] != "All":
            where_clauses.append("journal_published = %(is_journal)s")
            where_params["is_journal"] = filters["journal_status"] == "Journal Article"

        # Citation range
        low, high = filters["citation_range"]
        if filters["include_unknown_citations"]:
            where_clauses.append(
                "(citations BETWEEN %(cite_low)s AND %(cite_high)s OR citations IS NULL)"
            )
        else:
            where_clauses.append("citations BETWEEN %(cite_low)s AND %(cite_high)s")

        where_params["cite_low"] = low
        where_params["cite_high"] = high

        # Paper ID / title filters
        pf = filters.get("paper_filter", {"ids": set(), "titles": set()})
        id_patterns = [f"{i}%" for i in pf["ids"]]
        title_patterns = [f"%{t}%" for t in pf["titles"]]

        or_clauses = []

        if id_patterns:
            or_clauses.append("paper_id LIKE ANY(%(paper_id_patterns)s)")
            where_params["paper_id_patterns"] = id_patterns

        if title_patterns:
            or_clauses.append("title ILIKE ANY(%(title_patterns)s)")
            where_params["title_patterns"] = title_patterns

        if or_clauses:
            where_clauses.append("(" + " OR ".join(or_clauses) + ")")

    # Fetch results
    results = fetch_results(
        query_vec=query_vec,
        citation_weight=citation_weight,
        top_k=top_k,
        selected_sources=selected_sources,
        filter_clauses=where_clauses,
        filter_params=where_params,
    )
    st.toast(f"**Embed time:** {embed_time} &nbsp; **SQL time:** {time.time() - t0}", icon="⏱")

    # Display results
    if not results:
        st.warning("No results found for the current filters.")
        return

    for i, r in enumerate(results):
        with st.expander(
            f"***{r['title']}* &nbsp; | &nbsp; {', '.join(r['authors'])} &nbsp; | &nbsp; {r['source']}**",
            expanded=True,
        ):
            theorem_col, feedback_col = st.columns([15, 1])
            with theorem_col:
                with st.expander(f"{r['theorem_slogan']}\n"):
                    st.markdown(f"**{r['theorem_name']}:** {clean_latex_for_display(r['theorem_body'])}")
                    cit_str = "Unknown" if r['citations'] is None else str(r['citations'])
                    st.caption(f"**Citations:** {cit_str} | **Year:** {r['year']} | **Tag:** {r['primary_category']}")
            with feedback_col:
                @st.fragment
                def feedback():
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
                feedback()
                st.markdown(f"[Link]({r['link']})")

# Header and sidebar
st.set_page_config(page_title="Theorem Search Demo", layout="wide")
if "ga_loaded" not in st.session_state:
    components.html(
        f"""
        <script async src="https://www.googletagmanager.com/gtag/js?id={SAFE_GA_MEASUREMENT_ID}"></script>
        <script>
          window.dataLayer = window.dataLayer || [];
          function gtag(){{dataLayer.push(arguments);}}
          gtag('js', new Date());
          gtag('config', '{SAFE_GA_MEASUREMENT_ID}');
        </script>
        """,
        height=0,
    )
    st.session_state["ga_loaded"] = True
st.title("Math Theorem Search")
st.write("This tool finds mathematical theorems that are semantically similar to your query.")

# Load metadata for filtering
theorem_count = load_theorem_count()
authors_per_source = load_authors()
tags_per_source = load_tags()
all_sources = load_sources()
source_caps = load_source_caps()

if 'show_success' not in st.session_state:
    st.session_state['show_success'] = False
if not st.session_state['show_success']:
    st.toast(f"Successfully loaded {theorem_count} theorems from {len(all_sources)} sources. Ready to search!")
    st.session_state['show_success'] = True

# Sidebar filters
st.logo(image="../images/math-ai-logo.jpg", size="large", link="https://sites.math.washington.edu/ai/")
with st.sidebar:
    st.header("Search Filters")

    selected_sources = st.multiselect(
        "Filter by Source:",
        all_sources,
        default=all_sources,
        help="Select one or more sources to search from.",
    )

    top_k_results = 25
    top_k_results = st.slider("Number of Results", 1, 50, top_k_results)

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
                citation_range = (0, 1502)
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
user_query = st.text_input(
    "Enter your query:",
    "",
    placeholder="Example: The Jones polynomial is link invariant",
)
if st.button("Search"):
    if st.session_state.get("last_logged_query") is None:
        st.session_state["last_logged_query"] = ""
    if st.session_state.get("last_logged_query") != user_query:
        insert_query(user_query, filters)
        st.session_state["last_logged_query"] = user_query

    with st.spinner("Fetching theorems..."):
        search_and_display(user_query, filters)

st.divider()
st.markdown("To improve search quality, we store all user queries and feedback. Help us improve by upvoting the results you find useful, and downvoting ones that are not relevant.")
st.markdown("Please direct all feedback to [Vasily Ilin](mailto:vilin@uw.edu).")
