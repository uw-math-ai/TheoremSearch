#%%
import json
import numpy as np
from sentence_transformers import SentenceTransformer, util
import os
import re
import pandas as pd

#%%
# --- 1. Load the Embedding Model ---
def load_model(model_name='math-similarity/Bert-MLM_arXiv-MP-class_zbMath'):
    return SentenceTransformer(model_name, trust_remote_code=True)

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


#%%
queries = ["Trivial stabilizers in the fiber product imply representability of the projection.",
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
theorems = [
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

# Prompt:
# "I would like you to give me accurate summary of each statement. It has to be accurate. Keep LaTeX notation to a minimum. Aim between 2 and 6 sentences for each. Make sure to include the relevant info that might be used to query the statement."
slogans = [
    "Given morphisms f: X → Y and g: Z → Y of algebraic stacks, form the fiber product F = X ×_Y Z. If a point x ∈ F has trivial automorphism group, then f is representable at the image π₁(x) ∈ X under the first projection. This means near x, f behaves like a morphism between algebraic spaces rather than stacks.",

    "Let X be an algebraic stack with affine diagonal, and S an S₂ stack with an open subset U whose complement has codimension ≥ 2. If two morphisms f, g: S → X are isomorphic on U, the isomorphism extends uniquely to all of S. This gives an extension criterion for morphisms from S₂ stacks across codimension-two subsets.",

    "For a good moduli space π: 𝓧 → X with X separated, the subset of points x ∈ X where the fiber π⁻¹(x) → x is an isomorphism is open in X. That is, points where the stack structure of 𝓧 trivializes form an open subset of the moduli space.",

    "Let φ: 𝓧 → 𝓨 be a morphism between separated Deligne–Mumford stacks with coarse spaces X and Y such that X → Y is an isomorphism. Assume both stacks are S₂ and φ is an isomorphism over a dense open subset of 𝓨 with complement of codimension ≥ 2. Then O_𝓨 → φ_*O_𝓧 is an isomorphism, so φ is the relative coarse moduli space morphism.",

    "If an algebraic stack 𝓧 → X has a dense open U ⊂ X where 𝓧 ×_X U is Deligne–Mumford, there exists a larger stack 𝓧̃ containing 𝓧 as an open substack. This 𝓧̃ has the same good moduli space X and carries a line bundle L_DM such that its semistable locus is Deligne–Mumford and proper over X. If 𝓧 is a global quotient, so is 𝓧̃. Moreover, a morphism π: 𝓧̃ → 𝓧 exists, restricting to an isomorphism over U. This construction yields proper DM compactifications used in defining quasimap moduli spaces.",

    "Let S be a separated Deligne–Mumford stack of dimension 2 with finite quotient singularities, and let 𝓧 → X be a stack with a good moduli space. Given a diagram extending a map S\\{s} → 𝓧 compatible with a map S → X, there exists a unique S₂ Deligne–Mumford stack 𝓢 → S extending it. The morphism 𝓢 → S is a relative coarse moduli space, is representable, and is an isomorphism outside s. If S is smooth, then 𝓢 → S is globally an isomorphism.",

    "The inclusion of the quasimap stack 𝓠_{g,n}(𝓧, 𝓧_DM) into the larger moduli stack 𝔔_{g,n}(𝓧, 𝓧_DM) is an open embedding. Hence, 𝓠_{g,n}(𝓧, 𝓧_DM) is an algebraic stack locally of finite type over the twisted curve moduli space 𝔐_{g,n}^{tw}.",

    "Given a DVR R with generic point η, any n-marked stable quasimap over η admits a unique extension to a stable quasimap over Spec(R), possibly after a finite base change. This ensures the valuative criterion for properness of the quasimap moduli stack.",

    "If the stack 𝓧 satisfies certain extension-of-line-bundle assumptions, the quasimap moduli stack 𝓠_{g,n}(𝓧, 𝓧_DM, β) is of finite type. Thus, the space of quasimaps of class β has bounded geometry and finitely many components.",

    "For any stable quasimap (φ: C → 𝓧, Σ₁,…,Σₙ) of class β, the topological type of C, the number of stacky points, and their automorphism groups are bounded. This provides finiteness and boundedness properties essential for the moduli stack’s finite type.",

    "Assuming the extension-of-line-bundle condition, there exist a group G′, a character χ: G′ → G_m, and an action on affine space Aⁿ giving a locally closed embedding 𝓧 → [Aⁿ/G′]. The inverse image of the semistable locus under this embedding corresponds exactly to 𝓧_DM. Hence, 𝓧 can be realized as a quotient stack fitting into a GIT-type presentation.",

    "For 𝓧 = 𝓓𝓟_m^{CY} and its open substack 𝓧_DM = 𝓓𝓟_m^{KSBA}, the general construction of Theorem 1 applies. The quasimap stack 𝓠_g(𝓧, 𝓧_DM, β) compactifies families of maps π: (Y, cD) → C whose fibers lie in 𝓧, with conditions ensuring klt fibers (Q), stability or non-isotriviality (S), and correct numerical class (N). Its boundary parametrizes twisted families satisfying analogous conditions, describing degenerations where semi-log-canonical or S-equivalence behavior changes along special fibers."
]

# not used at the moment
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

# %%
import numpy as np
from sentence_transformers import util

# ---------- helpers: qrels ----------
# qrels can be:
#   {q_idx: [doc_idx, ...]}                 -> binary relevance (1)
#   {q_idx: {doc_idx: grade, ...}}          -> graded relevance (0..3)
# You can also build by strings via make_qrels_by_text().
def make_qrels_by_text(latex_texts, concept_texts, mapping):
    """
    mapping: dict[str query_text] -> list[str or (str, grade)]
    Returns qrels in index form with graded relevance if provided.
    """
    qrels = {}
    q_lookup = {q:i for i,q in enumerate(latex_texts)}
    d_lookup = {d:i for i,d in enumerate(concept_texts)}
    for q_text, items in mapping.items():
        q = q_lookup[q_text]
        if isinstance(items, dict):
            qrels[q] = {d_lookup[k]: v for k,v in items.items()}
        else:
            # list; allow either strings or (string, grade)
            out = {}
            for it in items:
                if isinstance(it, tuple):
                    d_text, rel = it
                    out[d_lookup[d_text]] = rel
                else:
                    out[d_lookup[it]] = 1
            qrels[q] = out
    return qrels

# ---------- ranking ----------
def rank_concepts(sim_matrix):
    """
    sim_matrix: (num_queries, num_docs)
    returns: list of arrays, each is doc indices sorted by descending score
    """
    return [np.argsort(-row) for row in sim_matrix]

# ---------- metrics ----------
def precision_at_k(ranked, qrels, k=3, binary=True):
    ps = []
    for q, order in enumerate(ranked):
        rels = qrels.get(q, {})
        hits = sum((1 if (d in rels and (rels[d] if not binary else rels[d] >= 1)) else 0)
                   for d in order[:k])
        ps.append(hits / k)
    return float(np.mean(ps))

def recall_at_k(ranked, qrels, k=3, binary=True):
    rs = []
    for q, order in enumerate(ranked):
        rels = qrels.get(q, {})
        if not rels:
            continue
        denom = sum(1 for v in rels.values() if (v if not binary else v >= 1))
        denom = max(denom, 1)
        hits = sum((1 if (d in rels and (rels[d] if not binary else rels[d] >= 1)) else 0)
                   for d in order[:k])
        rs.append(hits / denom)
    return float(np.mean(rs)) if rs else 0.0

def mrr(ranked, qrels):
    rrs = []
    for q, order in enumerate(ranked):
        rels = qrels.get(q, {})
        first = None
        for i, d in enumerate(order, start=1):
            if d in rels and rels[d] >= 1:
                first = i
                break
        rrs.append(1.0 / first if first else 0.0)
    return float(np.mean(rrs))

def average_precision_at_k(ranked, qrels, k=3):
    """
    Binary AP@k
    """
    aps = []
    for q, order in enumerate(ranked):
        rels = qrels.get(q, {})
        if not rels:
            aps.append(0.0); continue
        num_rel = sum(1 for v in rels.values() if v >= 1)
        if num_rel == 0:
            aps.append(0.0); continue
        hits, s = 0, 0.0
        for i, d in enumerate(order[:k], start=1):
            if d in rels and rels[d] >= 1:
                hits += 1
                s += hits / i
        denom = min(num_rel, k)
        aps.append(s / denom if denom > 0 else 0.0)
    return float(np.mean(aps))

def ndcg_at_k(ranked, qrels, k=3):
    """
    Graded nDCG@k (falls back to binary if all grades are 0/1).
    DCG uses gains = 2^rel - 1.
    """
    def dcg(gains):
        return sum(g/np.log2(i+2) for i,g in enumerate(gains))

    ndcgs = []
    for q, order in enumerate(ranked):
        rels = qrels.get(q, {})
        # predicted top-k gains
        gains = [ (2**rels.get(d, 0) - 1) for d in order[:k] ]
        dcg_k = dcg(gains)
        # ideal gains
        ideal = sorted((2**v - 1 for v in rels.values()), reverse=True)[:k]
        idcg_k = dcg(ideal) if ideal else 1.0
        ndcgs.append(dcg_k / idcg_k if idcg_k > 0 else 0.0)
    return float(np.mean(ndcgs))

# ---------- main entry ----------
def evaluate_retrieval(model, theorems, queries, qrels, top_k_report=3):
    # encode
    print("encoding")
    l_emb = model.encode(theorems, convert_to_tensor=True)
    c_emb = model.encode(queries, convert_to_tensor=True)
    print("creating sim_matrix")
    sim_matrix = util.cos_sim(l_emb, c_emb).cpu().numpy()

    print("ranking concepts")
    ranked = rank_concepts(sim_matrix)

    # metrics
    metrics = {
        "P@1": precision_at_k(ranked, qrels, k=1),
        "P@3": precision_at_k(ranked, qrels, k=3),
        "R@3": recall_at_k(ranked, qrels, k=3),
        "MRR": mrr(ranked, qrels),
        "MAP@3": average_precision_at_k(ranked, qrels, k=3),
        "nDCG@3": ndcg_at_k(ranked, qrels, k=3),
    }

    # per-query quick report
    reports = []
    for qi, order in enumerate(ranked):
        sims = sim_matrix[qi]
        topk = order[:top_k_report]
        row = {
            "query_idx": qi,
            "query": theorems[qi],
            "topk": [(int(di), queries[di], float(sims[di])) for di in topk],
            "relevant_docs": sorted([(int(di), int(rel)) for di,rel in qrels.get(qi, {}).items()],
                                    key=lambda x: -x[1]),
        }
        reports.append(row)
    return metrics, reports

#%%
# collect theorem slogans from rds

import dotenv
import pandas as pd
from ec2.rds.paginate import paginate_query
from ec2.rds.connect import get_rds_connection

# select context window to pull slogans from
# context_window = "body-only-v1"
context_window = 'body-and-summary-v1'


validation_set = pd.read_csv("validation_set.csv", header=0, index_col=0, dtype={"paper_id": str})
validation_set[context_window] = None
dotenv.load_dotenv()
conn = get_rds_connection()

for idx, row in validation_set.iterrows():

    paper_like = str(row['paper_id']) + '%'
    theorem_name = str(row['theorem'])
    query_1 = """
    SELECT theorem_id
    FROM theorem
    WHERE paper_id LIKE %s
    AND name = %s
    """
    try:
        with conn.cursor() as cur:
            cur.execute(query_1, (paper_like, theorem_name))
            cols = [d[0] for d in cur.description]
            rows_raw = cur.fetchall()
        query_2 = """
            SELECT slogan
            FROM theorem_slogan
            WHERE prompt_id = %s
            AND theorem_id = %s
        """
        with conn.cursor() as cur:
            cur.execute(query_2, (context_window, rows_raw[0][0]))
            cols = [d[0] for d in cur.description]
            rows_raw = cur.fetchall()
        validation_set.loc[idx, context_window] = rows_raw[0][0]
    except:
        print(f"theorem info not found for: {row['paper_id'], row['theorem']}")
        continue

print(validation_set[validation_set[context_window].notnull()])

validation_set.to_csv('validation_set.csv')


#%%
# Build graded qrels by text → text

# select context window to test
context_window = "body-and-summary-v1"

vals = pd.read_csv("validation_set.csv", header=0, index_col=0, dtype={"paper_id": str})
vals = vals[vals[context_window].notnull()]
queries = vals['query'].tolist()
theorem_slogans = vals[context_window].tolist()
mapping = {}
for i in range(len(vals)):
    mapping[queries[i]] = [(theorem_slogans[i], 3)]

qrels = make_qrels_by_text(
    queries,
    theorem_slogans,
    mapping
)

print("number of theorems testing: ", len(vals))
print("context window: ", context_window)

# Choose the embedder
# model_name = "google/embeddinggemma-300m"
# model_name = "Qwen/Qwen3-Embedding-0.6B"
# model_name = "math-similarity/Bert-MLM_arXiv-MP-class_zbMath"
model_name = "nvidia/llama-embed-nemotron-8b" # Qwen3 0.6B is the best of three embedders
model = load_model(model_name)

# Choose whether to use slogans or theorems
# metrics, per_query = evaluate_retrieval(model, theorems, queries, qrels, top_k_report=3)
metrics, per_query = evaluate_retrieval(model, queries, theorem_slogans, qrels, top_k_report=3) # slogans perform much better than raw theorems

# pretty-print metrics with 4 decimal places
rounded_metrics = {k: float(f"{v:.4f}") for k, v in metrics.items()}

explanations = {
    "P@1": "Precision at 1 — fraction of queries whose top-ranked document is relevant.",
    "P@3": "Precision at 3 — average fraction of relevant documents among the top 3 results.",
    "R@3": "Recall at 3 — average fraction of relevant documents retrieved in the top 3 results.",
    "MRR": "Mean Reciprocal Rank — average inverse rank of the first relevant result.",
    "MAP@3": "Mean Average Precision at 3 — average precision considering relevant docs up to rank 3.",
    "nDCG@3": "Normalized Discounted Cumulative Gain at 3 — graded ranking quality up to rank 3.",
}
print("Model: ", model_name)
print("Evaluation metrics:")
for key in ["P@1", "P@3", "R@3", "MRR", "MAP@3", "nDCG@3"]:
    val = rounded_metrics.get(key, metrics.get(key, 0.0))
    print(f"{key}: {val:.4f}  — {explanations.get(key)}")

for r in per_query[:3]:   # peek first 3 queries
    print(r["query_idx"], r["topk"], "relevant:", r["relevant_docs"])

# %%
