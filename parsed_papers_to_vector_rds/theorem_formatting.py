from embeddings import embed_texts
from slogans import generate_theorem_slogans

def get_theorem_metadata_and_embeddings(parsed_paper: dict) -> tuple[dict, list[dict]]:
    """
    Converts a parsed paper JSON into RDS-ready paper metadata and theorem embeddings.

    Parameters
    ----------
    parsed_paper: dict
        JSON object describing a paper's metadata and its theorems

    Returns
    -------
    theorem_metadata: dict
        RDS-ready objects describing the paper's metadata
    theorem_embeddings: list[dict]
        RDS-ready list of objects describing a theorem
    """

    global_notations = parsed_paper.get("global_notations", "")
    global_definitions = parsed_paper.get("global_definitions", "")
    global_assumptions = parsed_paper.get("global_assumptions", "")

    global_context_parts = []
    if global_notations:
        global_context_parts.append(f"**Global Notations:**\n{global_notations}")
    if global_definitions:
        global_context_parts.append(f"**Global Definitions:**\n{global_definitions}")
    if global_assumptions:
        global_context_parts.append(f"**Global Assumptions:**\n{global_assumptions}")

    global_context = "\n\n".join(global_context_parts)

    theorem_metadata = {
        # "paper_id": None,
        "title": parsed_paper.get("title"),
        "authors": parsed_paper.get("authors", []),
        "link": parsed_paper.get("url"),
        "last_updated": parsed_paper.get("last_updated"),
        "summary": parsed_paper.get("summary"),
        "journal_ref": parsed_paper.get("journal_ref"),
        "primary_category": parsed_paper.get("primary_category"),
        "categories": parsed_paper.get("categories"),
        "global_notations": global_notations,
        "global_definitions": global_definitions,
        "global_assumptions": global_assumptions
    }

    theorem_embeddings = []
    theorems = []

    for theorem in parsed_paper.get("theorems", []):
        theorems.append(theorem["content"])

        theorem_embeddings.append({
            # "id": None,
            # "paper_id": None,
            "theorem_name": theorem.get("type"),
            "theorem_slogan": None,
            "theorem_body": theorem.get("content"),
            "embedding": None
        })

    print(" > Creating theorem slogans")
    slogans = generate_theorem_slogans(theorems, global_context)

    print(" > Creating theorem embeddings")
    embeddings = embed_texts(slogans)

    for theorem_embedding, slogan, embedding in zip(theorem_embeddings, slogans, embeddings):
        theorem_embedding["theorem_slogan"] = slogan
        theorem_embedding["embedding"] = embedding

    return theorem_metadata, theorem_embeddings

    