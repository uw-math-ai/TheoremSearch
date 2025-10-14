#%%
import json
import numpy as np
from sentence_transformers import SentenceTransformer, util
import os
import re

#%%
# --- 1. Load the Embedding Model ---
def load_model():
    """
    Loads the specialized math embedding model from Hugging Face.
    """
    model = SentenceTransformer('math-similarity/Bert-MLM_arXiv-MP-class_zbMath')
    return model

def compare_embeddings(model, latex_texts, concept_texts, top_k=3):
    """
    Encode latex tokens and concept phrases, print pairwise similarities
    and top-k concept matches for each latex token.
    """
    # encode
    l_emb = model.encode(latex_texts, convert_to_tensor=True)
    c_emb = model.encode(concept_texts, convert_to_tensor=True)

    # cosine similarity matrix: rows = latex, cols = concepts
    sim_matrix = util.cos_sim(l_emb, c_emb).cpu().numpy()

    for i, latex in enumerate(latex_texts):
        sims = sim_matrix[i]
        best_idx = sims.argmax()
        print(f"{latex!r}  -> best match: {concept_texts[best_idx]!r} (score {sims[best_idx]:.4f})")
        # top-k matches
        topk = sims.argsort()[::-1][:top_k]
        print("  top matches:")
        for rank, idx in enumerate(topk, start=1):
            print(f"    {rank}. {concept_texts[idx]!r} (score {sims[idx]:.4f})")
        print()


if __name__ == "__main__":
    model = load_model()

    latex_tokens = [
        r"\R",
        r"\Z",
        r"\N",
        r"\Q",
        r"\C",
        r"\epsilon",
        r"\partial",
        r"\nabla",
        r"\forall",
        r"\exists",
        r"\sum",
        r"\int",
    ]

    concept_phrases = [
        "real numbers",
        "integers",
        "natural numbers",
        "rational numbers",
        "complex numbers",
        "epsilon (infinitesimal)",
        "partial derivative",
        "gradient (del operator)",
        "for all (universal quantifier)",
        "there exists (existential quantifier)",
        "summation (sigma)",
        "integral",
    ]

    compare_embeddings(model, latex_tokens, concept_phrases, top_k=3)
# %%
