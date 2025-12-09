"""
Helpers for embedding texts into vectors.
"""

from sentence_transformers import SentenceTransformer
import torch
import multiprocessing
from .embedders import EMBEDDERS

def get_embedder(embedder_alias: str):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer(EMBEDDERS[embedder_alias], device=device)
    model.eval()
    return model

def embed_texts(embedder, texts_to_embed: list[str], batch_size: int = 16):
    """
    Embeds a list of texts into vectors using multiprocessing if available.
    Returns a NumPy array for maximum efficiency.
    """
    torch.set_num_threads(multiprocessing.cpu_count())

    with torch.inference_mode():
        if len(texts_to_embed) < batch_size:
            embeddings = embedder.encode(
                texts_to_embed,
                normalize_embeddings=True,
                show_progress_bar=False,
                batch_size=batch_size
            )
        else:
            embeddings = embedder.encode_multi_process(
                texts_to_embed,
                pool=None,
                normalize_embeddings=True,
                show_progress_bar=True,
                batch_size=batch_size
            )

    return embeddings.tolist()
