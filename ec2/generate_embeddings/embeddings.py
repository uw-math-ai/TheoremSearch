"""
Helpers for embeddings texts into vectors.
"""

from sentence_transformers import SentenceTransformer
import torch
import os

def get_embedder():
    model = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B", device="cpu")
    model.eval()

    return model

def embed_texts(
    embedder,
    texts_to_embed: list[str],
    batch_size: int = 16
) -> list[list[float]]:
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
    torch.set_num_threads(1)
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")

    with torch.inference_mode():
        all_embeddings = embedder.encode(
            texts_to_embed,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=True,
            batch_size=batch_size
        )

    return all_embeddings.tolist()