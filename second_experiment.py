# try to use a different version of QWEN other that 0.6B (how big can I go on my GPU?)
#%%
# all papers by Erdos, most are easy to understand: https://users.renyi.hu/~p_erdos/Erdos.html
# ChatGPT chat asking to extract theorems from papers: https://chatgpt.com/share/688b9239-e5f0-8001-be04-296d005c8adf
# Erdos' paper we used: https://www.ams.org/journals/bull/1947-53-04/S0002-9904-1947-08785-1/S0002-9904-1947-08785-1.pdf
# The differential geometry paper we used: https://arxiv.org/abs/2507.22091
# Overleaf (for LaTeX): https://www.overleaf.com/8292382672fdvtwjpdqdth#e70ea4
# The embedding model: https://huggingface.co/Qwen/Qwen3-Embedding-4B

from sentence_transformers import SentenceTransformer

# Theorems extracted from 'Some remarks on the theory of graphs' by Erdos, 1947

theorems_1 = [

    # ------------------------------------------------------------------
    """Definitions and notation
    --------------------------
    • A *graph* G is a finite set of vertices in which some unordered
      pairs of vertices are connected by edges; multiple edges are
      forbidden and loops are not allowed.
    • The *complementary graph* G′ of G has the same vertex set; two
      vertices are adjacent in G′ iff they are **not** adjacent in G.
    • A *complete graph* (clique) of order m is a graph on m vertices
      in which every pair of vertices is joined by an edge.
    • For positive integers k and ℓ, let **f(k, ℓ)** be the least
      integer n with the following Ramsey–type property:
      every graph G on n vertices contains either
      – a complete subgraph of order k, **or**
      – its complement G′ contains a complete subgraph of order ℓ.

    Theorem I
    ---------
    For every integer k ≥ 3,
        2^{k/2} < f(k, k) < 4^{\\,k}.
    In other words, the size-Ramsey number of the diagonal case
    (k versus k) grows faster than 2^{k/2} and is bounded above by 4^{k}.
    """,

    # ------------------------------------------------------------------
    """Definitions and notation
    --------------------------
    • Let n be a positive integer and fix i ≤ k, i ≤ ℓ.
    • A *combination of order r* is any r-element subset of {1,…,n}.
    • A *collection* 𝒞 of combinations of order *i* is given.
      We say that a k-subset *covers* 𝒞 if it contains at least one
      member of 𝒞, and that an ℓ-subset is *homogeneous* for 𝒞 if **all**
      of its i-subsets lie in 𝒞.

    Ramsey’s Theorem (general form)
    -------------------------------
    For every triple of positive integers (i, k, ℓ) with i ≤ k and
    i ≤ ℓ there exists an integer **f(i, k, ℓ)** such that for every
    n ≥ f(i, k, ℓ) and every collection 𝒞 of i-subsets of {1,…,n}
    satisfying
       “every k-subset of {1,…,n} covers 𝒞,”
    there is an ℓ-subset of {1,…,n} that is homogeneous for 𝒞
    (i.e. every one of its i-subsets belongs to 𝒞).
    """,

    # ------------------------------------------------------------------
    """Definitions and notation
    --------------------------
    • Fix integers k ≥ 2 and ℓ ≥ 2.
    • Consider a strictly increasing sequence of
      (k−1)(ℓ−1)+1 positive integers a₁ < a₂ < ⋯.
      We write x ∣ y if x divides y.

    Theorem II (Erdős, 1947)
    ------------------------
    Among any (k−1)(ℓ−1)+1 positive integers arranged in
    increasing order, **either**
      – there exist k numbers no one of which divides any other,
        **or**
      – there exist ℓ numbers forming a divisibility chain
        a_{t₁} ∣ a_{t₂} ∣ ⋯ ∣ a_{t_ℓ}.

    The bound (k−1)(ℓ−1)+1 is best possible.
    """,

    # ------------------------------------------------------------------
    """Definitions and notation
    --------------------------
    • Let G be a graph on n := (k−1)(ℓ−1)+1 vertices.
    • Orient every edge of the complement G′ arbitrarily, subject only
      to the condition that no directed cycle is created
      (i.e. the orientation makes G′ a directed acyclic graph).
    • A *directed path of order ℓ* is a sequence of ℓ distinct vertices
      v₁→v₂→⋯→v_ℓ with each arc oriented from v_j to v_{j+1}.

    Theorem IIa
    -----------
    For the above parameters and every acyclic orientation of the
    complement G′, **either**
      – G contains a complete subgraph (clique) of order k, **or**
      – G′ contains a directed path on ℓ vertices.

    Grünwald and Milgram later removed the acyclicity assumption:
    the conclusion still holds for *every* orientation of G′.
    """
]

# Theorems extracted from 'Curvature operator and Euler number', 2025

theorems_2 = [

# ------------------------------------------------------------------
"""**Theorem 1 (Erdős–Huang–Tan, Thm. C7).**
_Context & notation needed_:
• *(X,g)* is a compact, smooth Riemannian manifold of real dimension 2 n.
•  χ(X) denotes its Euler characteristic; H¹\\_{dR}(X) its first de-Rham cohomology.
•  Let λ₁ ≤ … ≤ λ_{n(n−1)/2} be the eigen-values of the curvature operator of (X,g).
•  For integers 1 ≤ p ≤ ⌊n/2⌋, κ ≤ 0 and numbers D, Λ > 0 write

  ℳ(p, κ, D, Λ) := { compact Riemannian n-manifolds (X,g) with
   (a)    (λ₁ + … + λ_{n−p}) / (n−p) ≥ κ,
   (b)    diam(X,g) ≤ D,
   (c)    −κ D² = Λ² }.

---

If (X,g) is 2 n–dimensional, satisfies H¹\\_{dR}(X) ≠ 0, and
(X,g) ∈ ℳ(p, κ, D, Λ) with Λ ≤ C(n) for a universal positive constant C(n), then

1. If p = n,    χ(X) = 0.
2. If p = n − 1,  (−1)ⁿ χ(X) ≥ 0.""",

# ------------------------------------------------------------------
"""**Theorem 2 (Poincaré–Li–Petersen–Wink, Thm. T1).**
_Context & notation needed_:
•  (X,g) is a compact n–dimensional Riemannian manifold.
•  Ric(g) denotes its Ricci curvature, D(g) its diameter, Vol(g) its volume.
•  For b ≥ 0 let

  R(b) := D(g) / (b C(b)),  where C(b) is the unique positive root of
    x ∫₀ᵇ ( cosh t + x sinh t )^{n−1} dt = ∫₀^π sin^{\\,n−1}t dt.

•  Σ(n,p,q) is the sharp Lᵖ–Lᵠ Sobolev constant of the unit sphere Sⁿ.

---

Assume

  Ric(g) · D(g)² ≥ −(n−1) b².

Let 1 ≤ q < n, choose p with 1 ≤ p ≤ n q / (n − q).
For every f ∈ W¹,q(X) the following Poincaré–Sobolev inequalities hold:

  ‖ f − Vol(g)^{−1}∫_X f ‖\\_{Lᵖ} ≤ S_{p,q}\\; ‖df‖\\_{Lᵠ},

  ‖f‖\\_{Lᵖ} ≤ S_{p,q}\\; ‖df‖\\_{Lᵠ} + Vol(g)^{1/p − 1/q} ‖f‖\\_{Lᵠ},

with S_{p,q} = Vol(g)^{1/p − 1/q}\\; R(b)\\; Σ(n,p,q).""",

# ------------------------------------------------------------------
"""**Theorem 3 (Integral estimate for twisted harmonic forms, Thm. T3).**
_Context & notation needed_:
•  (X,g) is a compact n–dimensional Riemannian manifold.
•  θ is a smooth 1-form with dual vector field θ♯.
•  Define the twisted differential d\\_θ := d + θ ∧, its adjoint d\\_θ* = d* + i_{θ♯},
 and the twisted Dirac operator 𝔇\\_θ := d\\_θ + d\\_θ*.
•  ker 𝔇\\_θ := { α ∈ Ω^{even}(X) ∪ Ω^{odd}(X) : 𝔇\\_θ α = 0 }.

---

For every α ∈ ker 𝔇\\_θ we have the \\(L²\\) estimate

  ∫_X |θ♯|² |α|² ≤ C₁(n) ∫_X |∇θ♯| |α|²,

where C₁(n) is a universal constant depending only on the dimension.""",
]

theorems_0 = ["""

**Theorem (Edges in a finite tree).**
_Context & notation needed_:
•  A **graph** G = (V, E) is finite, simple, undirected.
•  A **tree** is a connected graph with no cycles (equivalently, an acyclic connected graph).
•  Let n := |V| (number of vertices) and m := |E| (number of edges).

---

Every finite tree satisfies

  m = n − 1.

"""]

theorems = theorems_0 + theorems_1 + theorems_2

model = SentenceTransformer("Qwen/Qwen3-Embedding-4B")

embeddings = model.encode(theorems)

# cosine similarity: cos(∠(u,v)) = u*v/(|u|*|v|). if u==v, then cos(∠(u,v))==1.
similarities = model.similarity(embeddings, embeddings)
similarities

# the first theorem is THE EXACT same theorem
# the next 4 are about graphs and combinatorics
# the last 3 are about differential geometry -- very different

user_query = "a tree on n vertices has n-1 edges"

query_embedding = model.encode(user_query)
print(model.similarity(query_embedding, embeddings))

# Prints: 0.7832, 0.3740, 0.2722, 0.3448, 0.3698, 0.2320, 0.1735, 0.1787