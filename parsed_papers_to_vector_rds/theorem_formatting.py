from embeddings import embed_texts
from openai import OpenAI
import os

def get_theorem_metadata_and_embeddings(parsed_paper: dict):
    """
    Converts a parsed paper JSON into an embedding-ready string.
    """
    prompt = "I would like you to give me accurate summary of the statement. It has to be accurate. Keep LaTeX notation to a minimum. Aim between 2 and 6 sentences for each. Make sure to include the relevant info that might be used to query the statement."

    client = OpenAI(api_key=os.getenv("OPENAI_KEY"))

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

    print(" > Creating theorem slogans")

    for i, theorem in enumerate(parsed_paper.get("theorems", [])):
        print(f"    > Working on theorem {i+1}'s slogan")

        texts_to_embed.append(theorem["content"])
        response = client.responses.create(
            model="gpt-5",
            input=[
                {"role": "user", "content": prompt + "\n" + theorem.get("content")}
            ]
        )

        theorem_embeddings.append({
            "id": None,
            "paper_id": None,
            "theorem_name": theorem.get("type"),
            "theorem_slogan": response.output_text,
            "theorem_body": theorem.get("content"),
            "embedding": None
        })

    print(" > Creating theorem embeddings")

    embeddings = embed_texts(texts_to_embed)

    for theorem_embedding, embedding in zip(theorem_embeddings, embeddings):
        theorem_embedding["embedding"] = embedding

    return theorem_metadata, theorem_embeddings

    