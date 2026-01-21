"""
Helpers for embedding texts into vectors.
"""

import os, multiprocessing, torch
from sentence_transformers import SentenceTransformer
from .embedders import EMBEDDERS

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
    texts_to_embed: list[str], 
    batch_size: int):
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

    with torch.inference_mode():
        if embedder.device.type == "cpu" and len(texts_to_embed) >= batch_size:
            nthreads = int(os.environ.get("SLURM_CPUS_PER_TASK", multiprocessing.cpu_count()))
            torch.set_num_threads(nthreads)
            pool = embedder.start_multi_process_pool()  # CPU workers
            try:
                emb = embedder.encode(
                    texts_to_embed, pool,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                    batch_size=batch_size,
                    prompt="Instruct: Represent the given math statement for retrieving related statement by natural language query.\nQuery:",
                )
            finally:
                embedder.stop_multi_process_pool(pool)
        else:
            emb = embedder.encode(
                texts_to_embed,
                normalize_embeddings=True,
                show_progress_bar=False,
                batch_size=batch_size,
                prompt="Instruct: Represent the given math statement for retrieving related statement by natural language query.\nQuery:",
            )

    return emb.tolist()
