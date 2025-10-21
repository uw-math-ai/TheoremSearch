from embeddings import embed_texts
from openai import OpenAI

def get_theorem_metadata_and_embeddings(parsed_paper: dict):
    """
    Converts a parsed paper JSON into an embedding-ready string.
    """
    prompt = "Suppose you are an expert in mathematics and Algebraic Geometry." \
    "Your task is to rewrite a LaTeX description of a theorem into a succinct " \
    "slogan that can accurately describe the theorem in 1-2 sentences with natural language" \
    " (no TeX formulas). Please return the slogan you come up with in quotation marks"
    with open("api_key.txt", "r") as f:
        API_KEY = f.read().strip() # open ai key

    client = OpenAI(api_key=API_KEY)

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
        "paper_id": None,
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
    texts_to_embed = []

    for theorem in parsed_paper.get("theorems", []):
        texts_to_embed.append(theorem["content"])

        print("Querying OpenAI...")
        response = client.responses.create(
            model="gpt-5",
            input=prompt + "\n" + theorem.get("content")
        )

        theorem_embeddings.append({
            "id": None,
            "paper_id": None,
            "theorem_name": theorem.get("type"),
            "theorem_slogan": response.output_text,
            "theorem_body": theorem.get("content"),
            "embedding": None
        })

    embeddings = embed_texts(texts_to_embed)

    for theorem_embedding, embedding in zip(theorem_embeddings, embeddings):
        theorem_embedding["embedding"] = embedding

    return theorem_metadata, theorem_embeddings

    