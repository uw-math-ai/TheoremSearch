import re
from dotenv import load_dotenv

load_dotenv()

SOURCE_FILTERS = {
    "Stacks Project": {
        "authors": False,
        "types": True,
        "tags": True,
        "paper_filter": False,
        "year": False,
        "journal": False,
        "citations": False,
    },
    "arXiv": {
        "authors": True,
        "types": True,
        "tags": True,
        "paper_filter": True,
        "year": True,
        "journal": True,
        "citations": True,
    },
    "ProofWiki": {
        "authors": False,
        "types": True,
        "tags": False,
        "paper_filter": False,
        "year": False,
        "journal": False,
        "citations": False,
    },
    "An Infinitely Large Napkin": {
        "authors": False,
        "types": True,
        "tags": False,
        "paper_filter": True,
        "year": False,
        "journal": False,
        "citations": False,
    },
    "CRing Project": {
        "authors": False,
        "types": True,
        "tags": False,
        "paper_filter": True,
        "year": False,
        "journal": False,
        "citations": False,
    },
    "HoTT Book": {
        "authors": False,
        "types": True,
        "tags": False,
        "paper_filter": False,
        "year": False,
        "journal": False,
        "citations": False,
    },
    "Open Logic Project": {
        "authors": False,
        "types": True,
        "tags": False,
        "paper_filter": False,
        "year": False,
        "journal": False,
        "citations": False,
    },
}

def active_filters(selected_sources):
    caps = {k: False for k in next(iter(SOURCE_FILTERS.values()))}
    for s in selected_sources:
        src_caps = SOURCE_FILTERS.get(s, {})
        for k, v in src_caps.items():
            caps[k] = caps[k] or v
    return caps

def metadata_sources(selected_sources, source_caps):
    return [
        s for s in selected_sources
        if source_caps.get(s, {}).get("has_metadata", False)
    ]

def serialize_filters(filters: dict) -> dict:
    return {
        "types": ",".join(filters.get("types", [])),
        "tags": ",".join(filters.get("tags", [])),
        "sources": ",".join(filters.get("sources", [])),
        "paper_filter": ",".join(
            list(filters.get("paper_filter", {}).get("ids", [])) +
            list(filters.get("paper_filter", {}).get("titles", []))
        ),
        "year_range": (
            f"{filters['year_range'][0]}–{filters['year_range'][1]}"
            if filters.get("year_range") else None
        ),
        "citation_range": (
            f"{filters['citation_range'][0]}–{filters['citation_range'][1]}"
            if filters.get("citation_range") else None
        ),
        "citation_weight": float(filters.get("citation_weight", 0.0)),
        "include_unknown_citations": str(filters.get("include_unknown_citations")),
        "top_k": int(filters.get("top_k", 0)),
    }

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

def json_safe(obj):
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [json_safe(v) for v in obj]
    if isinstance(obj, set):
        return sorted(json_safe(v) for v in obj)
    return obj