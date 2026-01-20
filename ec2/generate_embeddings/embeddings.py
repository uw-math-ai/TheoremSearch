"""
Helpers for embedding texts into vectors.
"""

from sentence_transformers import SentenceTransformer
import torch
import multiprocessing
from .embedders import EMBEDDERS
from typing import List

model = None
def _get_embedder(embedder_alias: str):
    global model

    if model is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = SentenceTransformer(EMBEDDERS[embedder_alias], device=device)
        model.eval()

    return model

def embed_texts(
    embedder_alias: str, 
    texts_to_embed: List[str], 
    batch_size: int
):
    """
    Embeds a list of texts into vectors.

    Parameters
    ----------
    embedder_alias : str
        Alias of embedder
    texts_to_embed : List[str]
        List of texts to embed
    batch_size : int
        Number of texts to embed at one time

    Returns
    -------
    embeddings : List[List[float]]
        List of embeddings
    """
    embedder = _get_embedder(embedder_alias)

    torch.set_num_threads(multiprocessing.cpu_count())

    with torch.inference_mode():
        if len(texts_to_embed) < batch_size:
            embeddings = embedder.encode(
                texts_to_embed,
                normalize_embeddings=True,
                show_progress_bar=False,
                batch_size=batch_size,
                prompt="Instruct: Represent the given math statement for retrieving related statement by natural language query. \nQuery:"
            )
        else:
            embeddings = embedder.encode_multi_process(
                texts_to_embed,
                pool=None,
                normalize_embeddings=True,
                show_progress_bar=False,
                batch_size=batch_size
            )

    return embeddings.tolist()
