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

    latex_tokens = ["Trivial stabilizers in the fiber product imply representability of the projection.",
                    "Isomorphisms over codimension ≥2 open subsets extend uniquely for stacks with affine diagonal.",
                    "Points with trivial stabilizers under a good moduli space form an open subset.",
                    "Isomorphism in codimension ≥2 and S_2 implies equality of structure sheaves.",
                    "Stacks with DM open and good moduli space admit proper DM compactifications.",
                    "Extension over a point yields a unique S_2 DM stack with representable morphism.",
                    "The stack of stable quasimaps is open in the ambient moduli space.",
                    "Stable quasimaps extend over DVRs after base change.",
                    "The quasimap stack is of finite type.",
                    "Geometry and automorphisms of stable quasimaps are bounded.",
                    "Semistable locus via GIT realizes the DM substack.",
                    "Stable quasimaps to KSBA-type stacks admit proper DM compactifications."
                    ]


    concept_phrases = [
        "one can check representability after fiber product",
        "two morphisms from a S2 algebraic stack to an algebraic stack, which are isomorphic on a big open, are isomorphic.",
        "The set of points where the good moduli space map is an isomorphism is open, when the good moduli space is separated.",
        "A map of S2 DM stacks which is an isomorphism on a big open and with isomorphic coarse moduli space is a relative coarse moduli space.",
        "every algebraic stack with dense properly stable locus admits an open embedding in another algebraic stack which contains a proper-Deligne Mumford stack.",
        "A map from a smooth punctured surface to an algebraic stack with a good moduli space extends if the map at the level of good moduli space extend.",
        "being stable is an open condition for quasimaps.",
        "The stack of stable quasimaps is proper.",
        "the stack of stable quasimaps is of finite type",
        "Bounding cohomological type of orbifold curve using class ",
        "an algebraic stack admits an embedding in quotient of affine space by G",
        "compact moduli of fibered CY using quasimaps"
    ]

    compare_embeddings(model, latex_tokens, concept_phrases, top_k=3)
# %%
