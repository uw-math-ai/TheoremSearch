import streamlit as st
from streamlit.components.v1 import html
import streamlit_antd_components as sac
import json
from sentence_transformers import SentenceTransformer
import os
import boto3
import psycopg2
from psycopg2.extensions import connection
from pgvector.psycopg2 import register_vector
import re
from collections import defaultdict
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
    register_vector(conn)
    return conn

ALLOWED_TYPES = [
    "theorem", "lemma", "proposition", "corollary"
]

ARXIV_ID_RE = re.compile(
    r'(?:arxiv\.org/(?:abs|pdf)/)?((?:\d{4}\.\d{4,5}|[a-z\-]+/\d{7}))',
    re.IGNORECASE
)

EMBED_TABLE = "theorem_embedding_qwen"

# Load the Embedding Model
@st.cache_resource
def load_model():
    try:
        model = SentenceTransformer('Qwen/Qwen3-Embedding-0.6B')
        return model
    except Exception as e:
        st.error(f"Error loading the embedding model: {e}")
        return None

def infer_type(name: str) -> str:
    if not name:
        return "theorem"
    lower = name.lower()
    for t in ALLOWED_TYPES:
        if t in lower:
            return t
    return "theorem"

@st.cache_data(ttl=60*60*24) # cache for 24 hours
def load_authors():
    conn = get_rds_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT unnest(p.authors) AS author
        FROM paper p
        WHERE p.authors IS NOT NULL
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    authors = sorted(r[0] for r in rows if r[0])
    return authors

@st.cache_data(ttl=60*60*24) # cache for 24 hours
def load_tags_per_source():
    conn = get_rds_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            CASE WHEN p.link ILIKE '%%arxiv.org%%'
                 THEN 'arXiv'
                 ELSE 'Stacks Project'
            END AS source,
            p.primary_category
        FROM paper p
        WHERE p.primary_category IS NOT NULL
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    tags_per_source = defaultdict(set)
    for source, cat in rows:
        tags_per_source[source].add(cat)

    return {src: sorted(cats) for src, cats in tags_per_source.items()}

@st.cache_data(ttl=60*60*24) # cache for 24 hours
def load_theorem_count():
    conn = get_rds_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM theorem;")
    (n,) = cur.fetchone()
    cur.close()
    conn.close()
    return int(n)

def extract_arxiv_id(s: str) -> str | None:
    """Return normalized arXiv ID if present in s (URL or raw), else None."""
    if not s:
        return None
    m = ARXIV_ID_RE.search(s.strip())
    return m.group(1) if m else None

def normalize_title(s: str) -> str:
    return (s or "").casefold().strip()

def parse_paper_filter(raw: str) -> dict:
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

def save_feedback(feedback, query, url, theorem_name, filters):
    conn = get_rds_connection()
    cur = conn.cursor()


def make_json_safe(obj):
    if isinstance(obj, dict):
        return {k: make_json_safe(v) for k, v in obj.items()}
    elif isinstance(obj, set):
        return list(obj)
    elif isinstance(obj, tuple):
        return list(obj)
    elif isinstance(obj, list):
        return [make_json_safe(v) for v in obj]
    elif hasattr(obj, "item"):
        return obj.item()
    else:
        return obj

# --- Search and Display ---
def search_and_display(query: str, model, filters: dict):
    if not filters['sources']:
        st.warning("Please select at least one source.")
        return

    citation_weight = float(filters['citation_weight'])

    # Encode query to numpy array
    query_vec = model.encode(query or "", normalize_embeddings=True, convert_to_numpy=True)

    where = []
    params = []

    # Source
    if filters['sources']:
        src_cases = []
        if 'arXiv' in filters['sources']:
            src_cases.append(" (p.link ILIKE '%%arxiv.org%%') ")
        if 'Stacks Project' in filters['sources']:
            src_cases.append(" (p.link NOT ILIKE '%%arxiv.org%%') ")
        if src_cases:
            where.append("(" + " OR ".join(src_cases) + ")")

    # Authors
    if filters['authors']:
        where.append(" p.authors && %s ")
        params.append(filters['authors'])

    # Tag/category
    if filters['tags']:
        where.append(" p.primary_category = ANY(%s) ")
        params.append(filters['tags'])

    # Year (arXiv only)
    if filters['year_range']:
        yr0, yr1 = filters['year_range']
        where.append("""
                ( (p.link ILIKE '%%arxiv.org%%' AND EXTRACT(YEAR FROM p.last_updated) BETWEEN %s AND %s)
                  OR (p.link NOT ILIKE '%%arxiv.org%%') )
            """)
        params.extend([yr0, yr1])

    # Journal status (arXiv only)
    if filters['journal_status'] != "All":
        if filters['journal_status'] == "Journal Article":
            where.append(" (p.link ILIKE '%%arxiv.org%%' AND p.journal_ref IS NOT NULL) ")
        elif filters['journal_status'] == "Preprint Only":
            where.append(" (p.link ILIKE '%%arxiv.org%%' AND p.journal_ref IS NULL) ")

    # Paper filter: arXiv id in link or title substring(s)
    pf = filters.get("paper_filter", {"ids": set(), "titles": set()})
    id_patterns = [f"%{i}%" for i in pf.get("ids", set())]
    title_patterns = [f"%{t}%" for t in pf.get("titles", set())]
    pf_clauses = []
    if id_patterns:
        pf_clauses.append(" p.link ILIKE ANY(%s) ")
        params.append(id_patterns)
    if title_patterns:
        pf_clauses.append(" p.title ILIKE ANY(%s) ")
        params.append(title_patterns)
    if pf_clauses:
        where.append("(" + " OR ".join(pf_clauses) + ")")

    # Result type
    if filters['types']:
        like_any = [f"%{t}%" for t in filters['types']]
        where.append(" lower(t.name) ILIKE ANY(%s) ")
        params.append(like_any)

    # Citations
    low, high = filters["citation_range"]
    include_unknown = filters["include_unknown_citations"]

    if include_unknown:
        where.append("( (p.citations BETWEEN %s AND %s) OR p.citations IS NULL )")
    else:
        where.append("( p.citations IS NOT NULL AND (p.citations BETWEEN %s AND %s) )")

    params.extend([low, high])

    conn = get_rds_connection()
    cur = conn.cursor()

    results = []

    # Fetch results from RDS

    if citation_weight == 0.0:
        sql = f"""
                WITH latest_slogan AS (
                    SELECT DISTINCT ON (ts.theorem_id)
                           ts.theorem_id, ts.slogan_id, ts.slogan
                    FROM theorem_slogan ts
                    ORDER BY ts.theorem_id, ts.slogan_id DESC
                )
                SELECT
                    p.paper_id,
                    p.title,
                    p.authors,
                    p.link,
                    p.last_updated,
                    p.summary,
                    p.journal_ref,
                    p.primary_category,
                    p.categories,
                    p.citations,
                    t.theorem_id,
                    t.name AS theorem_name,
                    t.body AS theorem_body,
                    ls.slogan AS theorem_slogan,
                    (1.0 - (e.embedding <#> %s::vector)) AS similarity
                FROM paper p
                JOIN theorem t        ON t.paper_id = p.paper_id
                JOIN latest_slogan ls ON ls.theorem_id = t.theorem_id
                JOIN {EMBED_TABLE} e  ON e.slogan_id   = ls.slogan_id
                {'WHERE ' + ' AND '.join(where) if where else ''}
                ORDER BY e.embedding <#> %s::vector ASC
                LIMIT %s;
            """
        exec_params = [query_vec, *params, query_vec, int(filters['top_k'])]

        cur.execute(sql, exec_params)
        rows = cur.fetchall()

        for (paper_id, title, authors, link, last_updated, summary, journal_ref,
             primary_category, categories, citations, theorem_id, theorem_name,
             theorem_body, theorem_slogan, similarity) in rows:
            link_str = link or ""
            source = "arXiv" if "arxiv.org" in link_str else "Stacks Project"
            inferred_type = infer_type(theorem_name or "")
            year = last_updated.year if last_updated else None

            results.append({
                "paper_id": paper_id,
                "authors": authors,
                "paper_title": title,
                "paper_url": link,
                "year": year,
                "primary_category": primary_category,
                "source": source,
                "type": inferred_type,
                "journal_published": bool(journal_ref),
                "citations": citations,
                "theorem_id": theorem_id,
                "theorem_name": theorem_name,
                "theorem_slogan": theorem_slogan,
                "theorem_body": theorem_body,
                "similarity": float(similarity),
                "score": float(similarity),
            })

    else:
        pool_size = max(50, int(filters['top_k']) * 10)

        sql = f"""
                WITH latest_slogan AS (
                    SELECT DISTINCT ON (ts.theorem_id)
                           ts.theorem_id, ts.slogan_id, ts.slogan
                    FROM theorem_slogan ts
                    ORDER BY ts.theorem_id, ts.slogan_id DESC
                ),
                candidates AS (
                    SELECT
                        p.paper_id,
                        p.title,
                        p.authors,
                        p.link,
                        p.last_updated,
                        p.summary,
                        p.journal_ref,
                        p.primary_category,
                        p.categories,
                        p.citations,
                        t.theorem_id,
                        t.name AS theorem_name,
                        t.body AS theorem_body,
                        ls.slogan AS theorem_slogan,
                        (1.0 - (e.embedding <#> %s::vector)) AS similarity
                    FROM paper p
                    JOIN theorem t        ON t.paper_id = p.paper_id
                    JOIN latest_slogan ls ON ls.theorem_id = t.theorem_id
                    JOIN {EMBED_TABLE} e  ON e.slogan_id   = ls.slogan_id
                    {'WHERE ' + ' AND '.join(where) if where else ''}
                    ORDER BY e.embedding <#> %s::vector ASC
                    LIMIT {pool_size}
                )
                SELECT
                    *,
                    (
                        similarity +
                        %s * CASE
                                WHEN citations IS NOT NULL AND citations > 0
                                THEN ln(citations::float)
                                ELSE 0
                             END
                    ) AS weighted_score
                FROM candidates
                ORDER BY weighted_score DESC, similarity DESC
                LIMIT %s;
            """

        exec_params = [query_vec, *params, query_vec, citation_weight, int(filters['top_k'])]

        cur.execute(sql, exec_params)
        rows = cur.fetchall()

        for (paper_id, title, authors, link, last_updated, summary, journal_ref,
             primary_category, categories, citations, theorem_id, theorem_name,
             theorem_body, theorem_slogan, similarity, weighted_score) in rows:
            link_str = link or ""
            source = "arXiv" if "arxiv.org" in link_str else "Stacks Project"
            inferred_type = infer_type(theorem_name or "")
            year = last_updated.year if last_updated else None

            results.append({
                "paper_id": paper_id,
                "authors": authors,
                "paper_title": title,
                "paper_url": link,
                "year": year,
                "primary_category": primary_category,
                "source": source,
                "type": inferred_type,
                "journal_published": bool(journal_ref),
                "citations": citations,
                "theorem_id": theorem_id,
                "theorem_name": theorem_name,
                "theorem_slogan": theorem_slogan,
                "theorem_body": theorem_body,
                "similarity": float(similarity),
                "score": float(weighted_score),
            })

    cur.close()
    conn.close()

    # Display results
    st.subheader(f"Found {len(results)} Matching Results")
    if not results:
        st.warning("No results found for the current filters.")
        return

    for i, info in enumerate(results):
        expander_title = f"**Result {i + 1} | Similarity: {info['score']:.4f} | {info.get('type', '').title()}**"
        with st.expander(expander_title, expanded=True):
            st.markdown(f"**Paper:** *{info.get('paper_title', 'Unknown')}*")
            st.markdown(f"**Authors:** {', '.join(info.get('authors') or []) or 'N/A'}")
            st.markdown(f"**Source:** {info.get('source')}")
            sac.buttons(
                items=
                [sac.ButtonsItem(label=info.get("paper_url"), icon="link-45deg", href=info.get("paper_url"))],
                variant="outline",
                color="violet",
                index=-1,
                key=f"link_{i}"
            )
            citations = info.get("citations")
            cit_str = "Unknown" if citations is None else str(citations)
            st.markdown(
                f"**Tag:** `{info.get('primary_category')}` | "
                f"**Citations:** {cit_str} | "
                f"**Year:** {info.get('year', 'N/A')}"
            )
            st.markdown("---")
            if info.get("theorem_slogan"):
                st.markdown(f"**Slogan:** {info['theorem_slogan']}\n")

            cleaned_content = clean_latex_for_display(info['theorem_body'])
            st.markdown(f"**{info['theorem_name'] or 'Theorem Body.'}**")
            st.markdown(cleaned_content)
            sac.buttons(
                items=
                [
                    sac.ButtonsItem(icon="hand-thumbs-up"),
                    sac.ButtonsItem(icon="hand-thumbs-down")
                ],
                variant="outline",
                color="violet",
                index=-1,
                key=f"feedback_{i}")


# --- Main App Interface ---
st.set_page_config(page_title="Theorem Search Demo", layout="wide")
st.title("Math Theorem Search")
st.write("This demo finds mathematical theorems that are semantically similar to your query.")

model = load_model()
theorem_count = load_theorem_count()
authors = load_authors()
tags_per_source = load_tags_per_source()

if model:
    st.success(f"Successfully loaded {theorem_count} theorems from arXiv and the Stacks Project. Ready to search!")
    # --- Sidebar filters ---
    st.logo(image="images/math-ai-logo.jpg", size="large", link="https://sites.math.washington.edu/ai/")
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
        top_k_results = 5

        if selected_sources:
            st.write("---")
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

            top_k_results = st.slider("Number of Results to Display:", 1, 20, 5)

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
    st.error("Could not load the model or data from RDS. Please check your RDS database connection and credentials.")