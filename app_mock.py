import streamlit as st
import re
import random

# --- 1. Mock Data and Placeholders ---

# The sources are now limited to arXiv and Stacks Project.
# The arXiv tag list has been expanded to include all official math categories.
AVAILABLE_TAGS = {
    "arXiv": [
        "math.AC", "math.AG", "math.AP", "math.AT", "math.CA", "math.CO",
        "math.CT", "math.CV", "math.DG", "math.DS", "math.FA", "math.GM",
        "math.GN", "math.GR", "math.GT", "math.HO", "math.IT", "math.KT",
        "math.LO", "math.MG", "math.MP", "math.NA", "math.NT", "math.OA",
        "math.OC", "math.PR", "math.QA", "math.RA", "math.RT", "math.SG",
        "math.SP", "math.ST"
    ],
    "Stacks Project": [
        "Sets", "Schemes", "Algebraic Stacks", "Étale Cohomology"
    ]
}

# Added the list of allowed types for the new filter.
ALLOWED_TYPES = [
    "theorem", "lemma", "proposition", "corollary", "definition", "remark", "assumption"
]

# The mock data is updated to use a type from the allowed list.
MOCK_THEOREMS_DATA = [
    {
        "paper_title": "On Thom Spectra, Orientability, and Cobordism",
        "paper_url": "https://arxiv.org/abs/alg-geom/9711020",
        "authors": ["Michael Atiyah", "Raoul Bott"],
        "citations": 250,
        "primary_math_tag": "math.AT",
        "type": "Theorem",
        "year": 1997,
        "source": "arXiv",
        "content": r"The cobordism ring $\Omega_n(X)$ is naturally isomorphic to the $n$-th stable homotopy group of the Thom spectrum $MT(X)$. That is, $\Omega_n(X) \cong \pi_n^{S}(MT(X))$",
        "global_context": "**Global Notations:**\nLet $X$ be a topological space and $V \to X$ be a vector bundle."
    },
    {
        "paper_title": "A paper about Knot Theory",
        "paper_url": "https://arxiv.org/abs/2103.00020",
        "authors": ["Edward Witten", "Vaughan Jones"],
        "citations": 150,
        "primary_math_tag": "math.GT",
        "type": "Definition",
        "year": 2022,
        "source": "arXiv",
        "content": r"For any link $L$, the Jones polynomial $V(L)$ is a Laurent polynomial in the variable $t^{1/2}$ with integer coefficients, characterized by the skein relation $t^{-1}V(L_+) - tV(L_-) = (t^{1/2} - t^{-1/2})V(L_0)$.",
        "global_context": "**Global Notations:**\nLet $V(L)$ be the Jones polynomial of a link $L$."
    },
    {
        "paper_title": "Heat Kernels and Dirac Operators",
        "paper_url": "https://arxiv.org/abs/hep-th/9409077",
        "authors": ["Nicole Berline", "Ezra Getzler", "Michèle Vergne"],
        "citations": 530,
        "primary_math_tag": "math.DG",
        "type": "Proposition",
        "year": 1994,
        "source": "arXiv",
        "content": r"Let $D$ be a Dirac operator on a compact Riemannian manifold $M$. Then the heat kernel $e^{-tD^2}$ admits an asymptotic expansion as $t \to 0^+$.",
        "global_context": "**Global Definitions:**\nA Dirac operator is a first-order differential operator whose square is a generalized Laplacian."
    },
    {
        "paper_title": "The Stacks Project",
        "paper_url": "https://stacks.math.columbia.edu/tag/0001",
        "authors": ["Aise Johan de Jong (Editor)"],
        "citations": 5000,
        "primary_math_tag": "Schemes",
        "type": "Remark", # Changed from "Tag" to "Remark"
        "year": 2023,
        "source": "Stacks Project",
        "content": r"An open source textbook and reference work on algebraic geometry. Its goal is to build up algebraic geometry from basic definitions to the research frontier.",
        "global_context": ""
    }
]

# --- 2. Model and Data Loading (Commented Out) ---
# ... (omitted for brevity)

# --- 3. Cleaning and Display Logic (Unchanged) ---
def clean_latex_for_display(text: str) -> str:
    """Cleans raw LaTeX for display in Streamlit. This function is kept for display purposes."""
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

# --- 4. Search and Display Logic (Modified for UI Mockup) ---
def search_and_display_mockup(query, filters):
    """
    Displays mock data instead of performing a real search.
    The displayed results will respect the filters set in the sidebar.
    """
    if not query:
        st.info("Please enter a search query to see the UI in action.")
        return

    # If no source is selected, prompt the user to select one.
    if not filters['sources']:
        st.info("Please select a source from the sidebar to begin filtering.")
        return

    # 1. Filter the mock data based on all sidebar selections
    filtered_results = []
    for item in MOCK_THEOREMS_DATA:
        # Check against each filter. `not filters[...]` handles empty filter selections.
        type_match = not filters['types'] or item['type'].lower() in filters['types']
        tag_match = not filters['tags'] or item['primary_math_tag'] in filters['tags']
        author_match = not filters['authors'] or any(author in item['authors'] for author in filters['authors'])
        source_match = item['source'] in filters['sources']
        citation_match = filters['citation_range'][0] <= item['citations'] <= filters['citation_range'][1]

        year_match = True
        if filters['year_range'] and item['source'] == 'arXiv':
            year_match = filters['year_range'][0] <= item['year'] <= filters['year_range'][1]

        if all([type_match, tag_match, author_match, source_match, year_match, citation_match]):
            filtered_results.append({
                "info": item,
                "similarity": random.uniform(0.75, 0.98)
            })

    filtered_results.sort(key=lambda x: x['similarity'], reverse=True)
    final_results = filtered_results[:filters['top_k']]

    # 2. Display the filtered mock results
    st.subheader(f"Top {len(final_results)} Matching Results (Mockup)")
    if not final_results:
        st.warning("No mock data items match your filter criteria.")
        return

    for i, result in enumerate(final_results):
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
            st.markdown("*Note: Linking to a specific page within an arXiv PDF is not directly possible.*")
            st.markdown("---")

            if info["global_context"]:
                cleaned_ctx = clean_latex_for_display(info["global_context"])
                st.markdown(f"> {cleaned_ctx.replace('\n', '\n> ')}")
                st.write("")

            cleaned_content = clean_latex_for_display(info['content'])
            st.markdown(cleaned_content)

# --- Main App Interface ---
st.set_page_config(page_title="Theorem Search UI", layout="wide")

st.title("Semantic Theorem Search (UI Proof of Concept)")
st.write("This is a mockup of the user interface. The search functionality is disabled and mock data is shown instead.")

st.success(f"Displaying {len(MOCK_THEOREMS_DATA)} mock theorems. Ready for UI testing!")

# --- Sidebar for Filters ---
with st.sidebar:
    st.header("Search Filters")

    # STEP 1: Display ONLY the source filter initially. It starts empty by default.
    all_sources = sorted(list(AVAILABLE_TAGS.keys()))
    selected_sources = st.multiselect(
        "Filter by Source(s):",
        all_sources,
        help="Select one or more sources to reveal more filters."
    )

    # Initialize all filter variables with default values.
    # This ensures the `filters` dictionary can be built even if no source is selected.
    selected_authors = []
    selected_types = []
    selected_tags = []
    year_range = None
    citation_range = (0, 1000000)
    top_k_results = 5

    # STEP 2: Only if the user has selected at least one source, show the other filters.
    if selected_sources:
        st.write("---") # Add a visual separator

        # Filter by Type
        selected_types = st.multiselect("Filter by Type:", ALLOWED_TYPES)

        # Filter by Author
        all_authors = sorted(list(set(author for item in MOCK_THEOREMS_DATA for author in item.get('authors', []))))
        selected_authors = st.multiselect("Filter by Author(s):", all_authors)

        # Filter by Tag (dynamically populated based on selected sources)
        tags_to_display = []
        for source in selected_sources:
            tags_to_display.extend(AVAILABLE_TAGS.get(source, []))
        tags_to_display = sorted(list(set(tags_to_display)))
        selected_tags = st.multiselect("Filter by Math Tag/Category:", tags_to_display)

        # Conditional Year Filter (only appears for arXiv)
        if 'arXiv' in selected_sources:
            year_range = st.slider(
                "Filter by Year (for arXiv):",
                min_value=1991, max_value=2025, value=(1991, 2025)
            )

        # Other Filters
        citation_range = st.slider(
            "Filter by Citations:",
            min_value=0, max_value=1000000, value=(0, 1000000)
        )
        top_k_results = st.slider("Number of results to display:", 1, 20, 5)

# Build the filters dictionary from the variables, which will either have user-selected
# values or the initial default values.
filters = {
    "authors": selected_authors,
    "types": selected_types,
    "tags": selected_tags,
    "sources": selected_sources,
    "year_range": year_range,
    "citation_range": citation_range,
    "top_k": top_k_results
}

# --- Search Bar and Results ---
user_query = st.text_input("Enter your query:", "")

search_and_display_mockup(user_query, filters)