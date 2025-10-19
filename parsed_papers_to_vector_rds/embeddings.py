from sentence_transformers import SentenceTransformer
import torch

def _get_embedder():
    return SentenceTransformer("math-similarity/Bert-MLM_arXiv-MP-class_zbMath")

def embed_texts(texts_to_embed: list[str]):
    embedder = _get_embedder()

    all_embeddings_tensor = embedder.encode(texts_to_embed, convert_to_tensor=True)
    all_embeddings = all_embeddings_tensor.detach().cpu().tolist()

    return all_embeddings