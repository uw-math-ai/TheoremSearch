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

    latex_tokens_text = ["Trivial stabilizers in the fiber product imply representability of the projection.",
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
    latex_tokens = [
        r"Let $f:\cX\to \cY$ and $g:\cZ\to \cY$ be morphisms of algebraic stacks, with $\cF:=\cX\times_\cY\cZ$. Let $x\in \cF$ such that $\Aut_{\cF}(x)=\{1\}$. Then $f$ is representable at $\pi_1(x)$, where $\pi_1:\cF\to \cX$ is the first projection.",
        r"Let $\cX$ be an algebraic stack with affine diagonal, let $S$ be an $S_2$ algebraic stack, and let $U\subset S$ an open subset with complement of codimension at least two. Assume we are given two morphisms $f,g: S\to \cX$ which are isomorphic when restricted on $U$. Then the isomorphism extends uniquely to $S$.",
        r"Let $\cX\to X$ a good moduli space, with $X$ separated. Then the set $\cS:=\{x\in X:\pi^{-1}(x)\to x$ is an isomorphism\} is open in $X$.",
        r"Let $\phi:\cX\to \cY$ be a morphism of separated Deligne--Mumford stacks with coarse moduli spaces $X$ and $Y$ respectively, and such that the morphism $X\to Y$ is an isomorphism. Assume that $\cX$ and $\cY$ are $S_2$, and that $\phi$ is an isomorphism over an open dense $V\subseteq \cY$ with complement of codimension at least two. Then the natural map $\cO_\cY\to \phi_*\cO_\cX$ is an isomorphism. In particular, $\phi$ is a relative coarse moduli space.",
        r"""Let $\cX$ be an algebraic stack with a good moduli space $p:\cX\to X$, and with a dense open $U\subseteq X$ such that $\cX\times_XU$ is Deligne--Mumford. Then there is an algebraic stack $\widetilde{\cX}$ with an open embedding $i:\cX\hookrightarrow \widetilde{\cX}$ such that: \begin{enumerate} \item $\widetilde{\cX}$ has a good moduli space which is isomorphic to $X$ via the inclusion $i$, \item there is a line bundle $\cL_{DM}$ on $\widetilde{\cX}$ such that $\widetilde{\cX}(\cL_{DM})^{ss}_X$ is  Deligne--Mumford and proper over $X$, \item if $\cX$ is a global quotient, then $\widetilde{\cX}$ can be chosen to be a global quotient, \item there is a morphism $\pi:\widetilde{\cX}\to \cX$ which is an isomorphism over $(p\circ \pi)^{-1}(U)$, \item the morphism $\pi\circ i$ is isomorphic to the identity.\end{enumerate} In particular, from \Cref{teo_intro_cX_contains_open_proper_dm}, if $\cX$ is a global quotient and one fixes an integer $g$ and a class $\beta$, there is a moduli space $\cQ_g(\widetilde{\cX},\widetilde{\cX}(\cL_{DM})^{ss}_X,\beta)$ of stable quasimaps to $\widetilde{\cX}$ which is a proper Deligne--Mumford stack.""",
        r"""Assume that $S$ is a separated Deligne--Mumford stack of dimension 2, with finite quotient singularities. Let $\cX$ be an algebraic stack with a good moduli space $\cX\to X$, and let $s\in S$ be a closed point of $S$. Assume that there is a diagram as follows: \[ \xymatrix{S\smallsetminus\{s\}\ar[d]\ar[r] & \cX\ar[d]\\S\ar[r]^f & X.} \] {Then there is an unique $S_2$ Deligne--Mumford stack $\cS$ with $\cS\to S$ a relative coarse moduli space that is an isomorphism on $S\smallsetminus \{s\}$, and such that there is an extension $\phi:\cS\to \cX$ which is representable. Such an extension is unique, the stack $\cS$ has finite quotient singularities, and if $S$ is smooth then $\cS\to S$ is an isomorphism.} """,
        r"The inclusion $\cQ_{g,n}(\cX,\cX_\dm)\to \mathfrak{Q}_{g,n}(\cX,\cX_\dm)$ is an open embedding. In particular, $\cQ_{g,n}(\cX,\cX_\dm)$ is algebraic and locally of finite type over $\mathfrak{M}_{g,n}^{\rm tw}$.",
        r"""We will adopt \Cref{notation_cX_and_cX_dm}, moreover let $R$ be a DVR, let $\eta$ be the generic point of $\spec(R)$ and $p$ the closed one. Let $(\phi_\eta:\sC_\eta\to \cX; \Sigma_{1},\ldots,\Sigma_{n})$ be an $n$-marked stable quasimap to $(\cX_{\dm},\cX)$, over $\eta$. Then, up to replacing $\spec(R)$ with a possibly ramified cover of it, there is a unique $n$-marked stable quasimap to $(\cX_{\dm},\cX)$ over $\spec(R)$ extending $(\phi_\eta:\sC_\eta\to \cX; p_{1},\ldots,p_{n})$. """,
        r"""Given $\cX$ satisfying \Cref{assumptions:extension of line bundle}, the algebraic stack $\cQ_{g,n}(\cX,\cX_\dm,\beta)$ is of finite type.""",
        r"Let $(\phi:\sC\to \cX,\Sigma_1,\ldots,\Sigma_n)$ be a stable quasimap of class $\beta$. Then the topological type of $C$, the number of stacky points of $\sC$ and the automorphism groups of the stacky points are bounded.",
        r"Assuming \Cref{assumptions:extension of line bundle}, there is a group $G'$, a character $\chi:G'\to \Gm$ and an action on $\bA^n$, such that there is a locally closed embedding $\iota:\cX\to [\bA^n/G']$ satisfying $\iota^{-1}([\bA^n(\Bbbk_\chi)^{ss}/G'])=\cX_\dm$.",
        r""" Set $\cX:=\cD\cP^{\CY}_m$ and $\cX_\dm=\cD\cP^{\operatorname{KSBA}}_m$. Then the assumptions of \Cref{teo_intro_cX_contains_open_proper_dm} apply for the inclusion $\cX_\dm\subseteq \cX$. In particular: \begin{enumerate} \item the stack $\cQ_g(\cX,\cX_\dm,\beta)$ compactifies the space of maps $\pi\colon(Y,cD)\to C$ with fibers in $\cX$ such that: \begin{itemize} \item[(Q)] the curve $C$ is smooth and the generic fiber of $\pi$ has klt singularities, \item[(S)] either $\omega_C$ is ample, or not all the fibers of $\pi$ are $S$-equivalent, \item[(N)] the family $\pi$ comes from a map $C\to \cX$ of class $\beta$ from a curve of genus $g$. \end{itemize} \item the boundary of $\cQ_g(\cX,\cX_\dm,\beta)$ parametrizes families $\pi:(\sY,c\sD)\to \sC$ of pairs in $\cX$ with fibers in $\cX$, fibered over a twisted curve $\sC$, such that: \begin{itemize} \item[(Q)] the set $\Delta:=\{p\in \sC:(\sY_p,(c+\epsilon)\sD_p)$ does \underline{not} have semi-log-canonical singularities for any $0<\epsilon \ll 1\}$ is a finite union of smooth points $\sC$, \item[(S)] if $\sR\subseteq \sC$ is an irreducible component such that $\deg(\omega_\sC |_\sR)< 0$, then not all the fibers of $\pi|_\sR\colon(\sY|_\sR,c\sD|_\sR)\to \sR$ are $S$-equivalent; whereas if $\deg(\omega_\sC |_\sR)=0$, then not all fibers of $\pi|_\sR$ are isomorphic, and \item[(N)] the family $\pi$ comes from a map $\sC\to \cX$ of class $\beta$ from a twisted curve of genus $g$. \end{itemize} \end{enumerate}""",
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
