"""
Helpers for embeddings texts into vectors.
"""

from sentence_transformers import SentenceTransformer
import torch

def _get_embedder():
    return SentenceTransformer("Qwen/Qwen3-Embedding-0.6B", device="cpu")

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

    with torch.no_grad():
        all_embeddings = embedder.encode(
            texts_to_embed,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=8
        )

    return all_embeddings.tolist()