import streamlit as st
import json
import numpy as np
from sentence_transformers import SentenceTransformer
import os
import boto3
import psycopg2
from psycopg2.extensions import connection
from pgvector.psycopg2 import register_vector
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
    register_vector(conn)
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
    "theorem", "lemma", "proposition"
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
    for t in ["theorem", "lemma", "proposition"]:
        if t in lower:
            return t
    return "theorem"

# Load Data from RDS
@st.cache_data
def load_papers_from_rds():
    """
    Loads the theorem data from the RDS database.
    Returns a list of theorem dictionaries with all necessary fields.
    """
    try:
        conn = get_rds_connection()
        cur = conn.cursor()

        # Fetch all papers with their theorems
        cur.execute("""
            WITH latest_slogan AS (SELECT DISTINCT
            ON (ts.theorem_id)
                ts.theorem_id, ts.slogan_id, ts.slogan
            FROM theorem_slogan ts
            ORDER BY ts.theorem_id, ts.slogan_id DESC
                )
            SELECT p.paper_id,
                   p.title,
                   p.authors,
                   p.link,
                   p.last_updated,
                   p.summary,
                   p.journal_ref,
                   p.primary_category,
                   p.categories,
                   t.name    AS theorem_name,
                   ls.slogan AS theorem_slogan,
                   t.body    AS theorem_body
            FROM paper p
                     JOIN theorem t ON t.paper_id = p.paper_id
                     LEFT JOIN latest_slogan ls ON ls.theorem_id = t.theorem_id
            ORDER BY p.paper_id, t.name;
        """)

        rows = cur.fetchall()
        cur.close()
        conn.close()

        all_theorems_data = []
        for row in rows:
            (paper_id, title, authors, link, last_updated, summary,
             journal_ref, primary_category, categories,
             theorem_name, theorem_slogan, theorem_body) = row

            # Determine source from url
            link_str = link or ""
            if link_str.startswith("http://arxiv.org") or link_str.startswith("https://arxiv.org"):
                source = "arXiv"
            else:
                source = "Stacks Project"

            # Determine type from name
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

def compute_score(similarity: float, citations: int, weight: float) -> float:
    c = int(citations) if citations is not None else 0
    if c == 0:
        return float(similarity)
    return float(similarity) + float(weight) * np.log(c)

# --- Search and Display ---
def search_and_display(query: str, model, filters: dict):
    if not filters['sources']:
        st.warning("Please select at least one source.")
        return

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

    # Filter in SQL
    if filters['types']:
        like_any = [f"%{t}%" for t in filters['types']]
        where.append(" lower(t.name) ILIKE ANY(%s) ")
        params.append(like_any)

    sql = f"""
            WITH latest_slogan AS (
                SELECT DISTINCT ON (ts.theorem_id)
                       ts.theorem_id, ts.slogan_id, ts.slogan, ts.model
                FROM theorem_slogan ts
                ORDER BY ts.theorem_id, ts.slogan_id DESC
            )
            SELECT
                p.paper_id, p.title, p.authors, p.link, p.last_updated, p.summary,
                p.journal_ref, p.primary_category, p.categories,
                t.theorem_id, t.name AS theorem_name, t.body AS theorem_body,
                ls.slogan AS theorem_slogan,
                (1.0 - (e.embedding <#> %s::vector)) AS similarity
            FROM paper p
            JOIN theorem t        ON t.paper_id = p.paper_id
            JOIN latest_slogan ls ON ls.theorem_id = t.theorem_id
            JOIN {EMBED_TABLE} e  ON e.slogan_id   = ls.slogan_id
            {'WHERE ' + ' AND '.join(where) if where else ''}
            ORDER BY e.embedding <#> %s::vector ASC
            LIMIT %s
        """
    exec_params = [query_vec, *params, query_vec, int(filters['top_k'])]

    conn = get_rds_connection()
    cur = conn.cursor()
    cur.execute(sql, exec_params)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    # Populate result fields
    items = []
    for (paper_id, title, authors, link, last_updated, summary, journal_ref,
         primary_category, categories, theorem_id, theorem_name, theorem_body,
         theorem_slogan, similarity) in rows:

        # Determine source from url
        link_str = link or ""
        source = "arXiv" if link_str.startswith(
            ("http://arxiv.org", "https://arxiv.org")) or "arxiv.org" in link_str else "Stacks Project"

        inferred_type = infer_type(theorem_name or "")

        items.append({
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
            "similarity": float(similarity),
        })

    # Citations
    if 'arXiv' in filters['sources']:
        with st.spinner("Fetching citations..."):
            add_citations(items)
    for it in items:
        # Compute weighted score if applicable
        it["score"] = compute_score(it["similarity"], it.get("citations"), citation_weight)

    # Sort results by weighted score, then cosine similarity, then paper id
    items.sort(key=lambda x: (x["score"], x["similarity"], str(x.get("paper_id"))), reverse=True)

    # Display results
    st.subheader(f"Found {len(items)} Matching Results")
    if not items:
        st.warning("No results found for the current filters.")
        return

    for i, info in enumerate(items):
        expander_title = f"**Result {i + 1} | Similarity: {info['score']:.4f} | {info.get('type', '').title()}**"
        with st.expander(expander_title, expanded=True):
            st.markdown(f"**Paper:** *{info.get('paper_title', 'Unknown')}*")
            st.markdown(f"**Authors:** {', '.join(info.get('authors') or []) or 'N/A'}")
            st.markdown(f"**Source:** {info.get('source')} ({info.get('paper_url')})")
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
            st.markdown("---")
            # FOR TESTING ONLY
            st.caption(f"Paper ID: {info['paper_id']}")
            if info['citations'] is None or info['citations'] == 0:
                log = 0
            else:
                log = np.log(info['citations'])
            st.caption(
                f"base_cosine={info['similarity']:.4f} | log(cit)={log:.4f} | weight={filters['citation_weight']:.2f}")

# --- Main App Interface ---
st.set_page_config(page_title="Theorem Search Demo", layout="wide")
st.title("Math Theorem Search")
st.write("This demo finds mathematical theorems that are semantically similar to your query.")

model = load_model()
theorems_data = load_papers_from_rds()

if model and theorems_data:
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
        paper_filter = ""
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
                citation_range = st.slider("Filter by Citations:", 0, 1000, 1000, step=10)
                citation_weight = st.slider("Citation Weight:", 0.0, 1.0, 0.0, step=0.01,
                                            help="If nonzero, results are ranked by base_score $+$ weight $\\times$ "
                                                 "$\\log($citations$)$.")
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
        search_and_display(user_query, model, filters)
else:
    st.error("Could not load the model or data from RDS. Please check your RDS database connection and credentials.")
