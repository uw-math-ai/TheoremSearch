import streamlit as st
import streamlit_antd_components as sac
from sentence_transformers import SentenceTransformer
import re
from latex_clean import clean_latex_for_display
from db import (get_rds_connection, row_to_dict, load_authors, load_theorem_count,
                load_tags_per_source, insert_feedback, serialize_filters)

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
    if not filters['sources']:
        st.warning("Please select at least one source.")
        return

    serialized_filters = serialize_filters(filters)

    citation_weight = float(filters['citation_weight'])
    top_k = int(filters["top_k"])

    # Encode query
    query_vec = model.encode(query or "", normalize_embeddings=True, convert_to_numpy=True)

    where = []
    params = []

    def metadata_safe(condition: str) -> str:
        """
        Apply filters to sources that have metadata (e.g., arXiv).
        Sources without metadata are excluded (e.g., Stacks Project).
        """
        return f"(NOT has_metadata OR {condition})"

    # Source
    where.append("source = ANY(%s)")
    params.append(filters["sources"])

    # Authors
    if filters['authors']:
        where.append("authors && %s")
        params.append(filters["authors"])

    # Tag/category
    if filters['tags']:
        where.append(metadata_safe("primary_category = ANY(%s)"))
        params.append(filters["tags"])

    # Year
    if filters['year_range']:
        y0, y1 = filters["year_range"]
        where.append(metadata_safe("year BETWEEN %s AND %s"))
        params.extend([y0, y1])

    # Journal status
    if filters['journal_status'] != "All":
        where.append(metadata_safe("journal_published = %s"))
        params.append(filters["journal_status"] == "Journal Article")

    # Paper filter: arXiv id in link or title substring(s)
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

    # Result type
    if filters['types']:
        where.append("theorem_type = ANY(%s)")
        params.append(filters["types"])

    # Citations
    low, high = filters["citation_range"]
    if filters["include_unknown_citations"]:
        where.append(metadata_safe("(citations BETWEEN %s AND %s OR citations IS NULL)"))
    else:
        where.append(metadata_safe("citations BETWEEN %s AND %s"))
    params.extend([low, high])

    where_sql = "WHERE " + " AND ".join(where)

    conn = get_rds_connection()
    cur = conn.cursor()

    # Fetch results from RDS
    if citation_weight == 0.0:
        # Unweighted search
        sql = f"""
                SELECT *,
                       (1.0 - (embedding <#> %s::vector)) AS similarity
                FROM theorem_search_qwen
                {where_sql}
                ORDER BY embedding <#> %s::vector
                LIMIT %s;
            """
        exec_params = [query_vec, *params, query_vec, top_k]
        cur.execute(sql, exec_params)
        rows = cur.fetchall()
        results = [
            {**row_to_dict(cur, row),
             "similarity": row[-1],
             "score": row[-1]}
            for row in rows
        ]
    else:
        # Weighted search
        pool_size = max(50, top_k * 10)
        sql = f"""
                WITH candidates AS (
                    SELECT *,
                           (1.0 - (embedding <#> %s::vector)) AS similarity
                    FROM theorem_search_qwen
                    {where_sql}
                    ORDER BY embedding <#> %s::vector
                    LIMIT {pool_size}
                )
                SELECT *,
                       (
                           similarity +
                           %s * CASE
                                  WHEN citations IS NOT NULL AND citations > 0
                                  THEN ln(citations::float)
                                  ELSE 0
                                END
                       ) AS score
                FROM candidates
                ORDER BY score DESC, similarity DESC
                LIMIT %s;
            """
        exec_params = [
            query_vec, *params,
            query_vec,
            citation_weight,
            top_k
        ]
        cur.execute(sql, exec_params)
        rows = cur.fetchall()
        results = [
            {**row_to_dict(cur, row),
             "similarity": row[-3],
             "score": row[-1]}
            for row in rows
        ]
    cur.close()
    conn.close()

    # --- Display results ---
    st.subheader(f"Found {len(results)} Matching Results")
    if not results:
        st.warning("No results found for the current filters.")
        return

    for i, r in enumerate(results):
        with st.expander(
                f"**Result {i + 1} | Similarity: {r['score']/2:.4f} | {r['theorem_type'].title()}**",
                expanded=True
        ):
            st.markdown(f"**Paper:** *{r['title']}*")
            st.markdown(f"**Authors:** {', '.join(r['authors']) or 'N/A'}")
            st.markdown(f"**Source:** {r['source']}")
            sac.buttons(
                items=
                [sac.ButtonsItem(label=r['link'], icon="link-45deg", href=r['link'])],
                variant="outline",
                color="violet",
                index=-1,
                key=f"link_{i}"
            )
            citations = r['citations']
            cit_str = "Unknown" if citations is None else str(citations)
            st.markdown(
                f"**Tag:** `{r['primary_category']}` | "
                f"**Citations:** {cit_str} | "
                f"**Year:** {r['year']}"
            )
            st.markdown("---")
            st.markdown(f"**Slogan:** {r['theorem_slogan']}\n")
            st.markdown(f"**{r['theorem_name'] + '.' or 'Theorem Body.'}**")
            st.markdown(clean_latex_for_display(r["theorem_body"]))
            feedback = st.feedback(
                "thumbs",
                key=f"feedback_{r['slogan_id']}"
            )
            if feedback is not None:
                submitted_key = f"submitted_{r['slogan_id']}"
                if not st.session_state.get(submitted_key, False):
                    conn = get_rds_connection()
                    payload = {
                        "feedback": 1 if feedback == "👍" else -1,
                        "query": query,
                        "url": r["link"],
                        "theorem_name": r["theorem_name"],
                        "authors": ", ".join(r["authors"]) if r["authors"] else None,
                        **serialized_filters,
                    }
                    insert_feedback(conn, payload)
                    conn.close()
                    st.session_state[submitted_key] = True
                    st.success("Thank you for the feedback!")

# --- Main App Interface ---
st.set_page_config(page_title="Theorem Search Demo", layout="wide")
st.title("Math Theorem Search")
st.write("This tool finds mathematical theorems that are semantically similar to your query.")

conn = get_rds_connection()
model = load_model()
theorem_count = load_theorem_count(conn)
authors = load_authors(conn)
tags_per_source = load_tags_per_source(conn)
conn.close()

if model:
    st.success(f"Successfully loaded {theorem_count} theorems from arXiv and the Stacks Project. Ready to search!")
    # --- Sidebar filters ---
    st.logo(image="../images/math-ai-logo.jpg", size="large", link="https://sites.math.washington.edu/ai/")
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
        paper_filter = ""
        year_range, journal_status = None, "All"
        citation_range = (0, 1000)
        citation_weight = 0.0
        include_unknown_citations = True
        top_k_results = 10

        if selected_sources:
            st.write("---")
            ALLOWED_TYPES = [
                "theorem", "lemma", "proposition", "corollary"
            ]
            selected_types = st.multiselect("Filter by Type:", ALLOWED_TYPES)
            selected_authors = st.multiselect("Filter by Author(s):", authors)

            # Tags per selected source(s)
            union_tags = sorted({
                t
                for s in selected_sources
                for t in tags_per_source.get(s, [])
                if t
            })
            selected_tags = st.multiselect("Filter by Tag/Category:", union_tags)

            paper_filter = st.text_input("Filter by Paper",
                                             value="",
                                             placeholder="e.g., 2401.12345, Finite Hilbert stability",
                                             help="Filter by title substring or arXiv ID/URL. Use commas for multiple.")

            if 'arXiv' in selected_sources:
                year_range = st.slider("Filter by Year:", 1991, 2025, (1991, 2025))
                journal_status = st.radio("Publication Status:",
                                          ["All", "Journal Article", "Preprint Only"],
                                          horizontal=True)
                citation_range = st.slider("Filter by Citations:", 0, 1000, (0,1000), step=10)
                citation_weight = st.slider("Citation Weight:", 0.0, 1.0, 0.0, step=0.01,
                                            help="If nonzero, results are ranked by base_score $+$ weight $\\times$ "
                                                 "$\\log($citations$)$. This will increase search time."
                                            )
                include_unknown_citations = st.checkbox(
                    "Include entries with unknown citation counts",
                    value=True,
                    help="If unchecked, results with unknown citation counts are excluded."
                )

            top_k_results = st.slider("Number of Results to Display:", 1, 20, 10)


    def parse_paper_filter(raw: str) -> dict:
        """
        Parse user input into two sets: arXiv IDs and title substrings.
        Multiple entries are comma-separated.
        e.g. "2401.12345, Optimal Transport" -> {"ids":{"2401.12345"}, "titles":{"optimal transport"}}
        """
        ids, titles = set(), set()
        if not raw:
            return {"ids": ids, "titles": titles}
        for token in [t.strip() for t in raw.split(",") if t.strip()]:
            def extract_arxiv_id(s: str) -> str | None:
                # Return normalized arXiv ID if present in s, else None
                if not s:
                    return None
                arxiv_id_re = re.compile(
                    r'(?:arxiv\.org/(?:abs|pdf)/)?(\d{4}\.\d{4,5}|[a-z\-]+/\d{7})',
                    re.IGNORECASE
                )
                m = arxiv_id_re.search(s.strip())
                return m.group(1) if m else None

            arx = extract_arxiv_id(token)
            if arx:
                ids.add(arx.lower())
            else:
                def normalize_title(s: str) -> str:
                    return (s or "").casefold().strip()

                titles.add(normalize_title(token))
        return {"ids": ids, "titles": titles}

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

    user_query = st.text_input("Enter your query:", "")
    if st.button("Search") or user_query:
        with st.spinner("Fetching theorems..."):
            search_and_display(user_query, model, filters)
else:
    st.error("Could not load the model or data from RDS. Please try again later.")