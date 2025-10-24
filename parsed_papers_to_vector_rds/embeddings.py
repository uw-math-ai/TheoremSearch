"""
Helpers for embeddings texts into vectors.
"""

from sentence_transformers import SentenceTransformer

def _get_embedder():
    return SentenceTransformer("math-similarity/Bert-MLM_arXiv-MP-class_zbMath")

def embed_texts(texts_to_embed: list[str]) -> list[list[float]]:
    """
    Embeds a list of texts into vectors.

    Parameters
    ----------
    texts_to_embed: list[str]
        A list of strings to embed

    Returns
    -------
    all_embeddings: list[list[float]]
        An array of embedding vectors
    """

    embedder = _get_embedder()

    all_embeddings_tensor = embedder.encode(texts_to_embed, convert_to_tensor=True)
    all_embeddings = all_embeddings_tensor.detach().cpu().tolist()

    return all_embeddings