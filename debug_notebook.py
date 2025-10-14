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

# --- 2. Load and Prepare the Data ---
def load_and_prepare_data(paper_files):
    """
    Loads theorem data from the specified JSON files and prepares it for embedding.
    """
    all_theorems_data = []
    for file_path in paper_files:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

            global_notations   = data.get("global_notations", "")
            global_definitions = data.get("global_definitions", "")
            global_assumptions = data.get("global_assumptions", "")

            global_context_parts = []
            if global_notations:
                global_context_parts.append(f"**Global Notations:**\n{global_notations}")
            if global_definitions:
                global_context_parts.append(f"**Global Definitions:**\n{global_definitions}")
            if global_assumptions:
                global_context_parts.append(f"**Global Assumptions:**\n{global_assumptions}")

            global_context = "\n\n".join(global_context_parts)
            paper_url     = data.get("url", "")
            paper_title   = data.get("title", "N/A")

            for theorem in data.get("theorems", []):
                all_theorems_data.append({
                    "paper_title":    paper_title,
                    "paper_url":      paper_url,
                    "type":           theorem["type"],
                    "content":        theorem["content"],
                    "global_context": global_context,
                    "text_to_embed":  f"{global_context}\n\n**{theorem['type'].capitalize()}:**\n{theorem['content']}"
                })

    return all_theorems_data

# --- 3. The Search and Display Function ---
def clean_latex_for_display(text: str) -> str:
    """
    Cleans raw LaTeX for display in Streamlit, with direct \FPlint replacement.
    """
    # 1. Force‐replace any \FPlint or \FPInt with \dashint
    text = text.replace(r'\FPlint', r'\dashint')
    text = text.replace(r'\FPInt',  r'\dashint')

    # 2. Strip out metadata and macro definitions
    text = re.sub(
        r'\\(DeclareMathOperator|newcommand|renewcommand)\*?\{.*?\}\{.*?\}',
        '',
        text,
        flags=re.DOTALL
    )
    text = re.sub(
        r'\\(label|ref|cite|eqref|footnote|footnotetext|def|let|alert)\{.*?\}',
        '',
        text
    )

    # 3. Handle block environments (\begin{…}\end{…}, \[ … \])
    def wrap_env(match):
        content = match.group(2).strip()
        return f"$$\n\\begin{{aligned}}\n{content}\n\\end{{aligned}}\n$$"

    text = re.sub(
        r'\\begin\{(equation|align|gather|multline|flalign|dmath)\*?\}(.*?)\\end\{\1\*?\}',
        wrap_env,
        text,
        flags=re.DOTALL
    )
    text = re.sub(r'\\\[(.*?)\\\]', r'$$\n\1\n$$', text, flags=re.DOTALL)

    # 4. Wrap any stray line containing '&' as an aligned block
    lines = text.split('\n')
    processed = []
    for line in lines:
        if '&' in line:
            processed.append(f"$$\n\\begin{{aligned}}\n{line}\n\\end{{aligned}}\n$$")
        else:
            processed.append(line)
    text = '\n'.join(processed)

    # 5. Convert inline math \(...\) → $...$
    text = re.sub(r'\\\((.*?)\\\)', r'$\1$', text)

    # 6. Final cleanup: strip leftover \begin/\end and normalize newlines
    text = re.sub(r'\\begin\{.*?\}', '', text, flags=re.DOTALL)
    text = re.sub(r'\\end\{.*?\}', '', text, flags=re.DOTALL)
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()

#%%
# debug

model = load_model()

PARSED_DIR = "./parsed_papers"
paper_files = [
    os.path.join(PARSED_DIR, f)
    for f in os.listdir(PARSED_DIR)
    if f.endswith('.json')
]

theorems_data = load_and_prepare_data(paper_files)

corpus_texts      = [item['content'] for item in theorems_data]
corpus_embeddings = model.encode(corpus_texts, convert_to_tensor=True)
print(f"Embedded {len(theorems_data)} theorems from {len(paper_files)} papers. Ready to search!")

query = "Finite time blowup for an averaged Navier-Stokes equation]\\label{main}  There exists a symmetric averaged Euler bilinear operator $\\tilde B: H^{10}_\\df(\\R^3) \\times H^{10}_\\df(\\R^3) \\to H^{10}_\\df(\\R^3)^*$ obeying the cancellation property \\eqref{cancellation-2} for all $u \\in H^{10}_\\df(\\R^3)$, and a Schwartz divergence-free vector field $u_0$, such that there is no global-in-time mild solution $u: [0,+\\infty) \\to H^{10}_\\df(\\R^3)$ to the averaged Navier-Stokes equation \\eqref{ns-modified} with initial data $u_0$."

embeddings_db = corpus_embeddings

#%%
query_emb      = model.encode(query, convert_to_tensor=True)
cosine_scores  = util.cos_sim(query_emb, embeddings_db)[0]
top_indices    = np.argsort(-cosine_scores.cpu())[:5]

#%%
for i, idx in enumerate(top_indices):
    idx        = idx.item()
    similarity = cosine_scores[idx].item()
    info       = theorems_data[idx]

    expander_title = (
        f"**Result {i+1} | Similarity: {similarity:.4f} | "
        f"Type: {info['type'].capitalize()}**"
    )
    print(f"**Paper:** *{info['paper_title']}*")
    print(f"**Source:** [{info['paper_url']}]({info['paper_url']})")

    if info["global_context"]:
        cleaned_ctx    = clean_latex_for_display(info["global_context"])
        blockquote_ctx = "> " + cleaned_ctx.replace("\n", "\n> ")
        print(blockquote_ctx)
        print("")

    cleaned_content = clean_latex_for_display(info['content'])
    print(cleaned_content)

#%%
# compute the similarity to the theorems from paper 1402.0290v3_analysis, bc this is the Terence Tao paper

# Find indices of theorems containing the substring "Finite time blowup" (case-insensitive)
search = "Finite time blowup"
search_lower = search.lower()

matching_indices = [
    i for i, item in enumerate(theorems_data)
    if search_lower in item.get("content", "").lower() or search_lower in item.get("text_to_embed", "").lower()
]

print("Matching indices:", matching_indices)
for i in matching_indices[:1]:
    info = theorems_data[i]
    print(f"Index {i}: Paper='{info['paper_title']}', Type='{info['type']}', URL='{info['paper_url']}'")

#%%
tao_theorem = r"""**Global Notations:**
We use $X=O(Y)$ or $X \lesssim Y$ to denote the estimate $|X| \leq CY$, for some quantity $C$ (which we call the \emph{implied constant}). If we need the implied constant to depend on a parameter (e.g. $k$), we will either indicate this convention explicitly in the text, or use subscripts, e.g. $X = O_k(Y)$ or $X \lesssim_k Y$. If $\xi$ is an element of $\R^3$, we use $|\xi|$ to denote its Euclidean magnitude. For $\xi_0 \in \R^3$ and $r>0$, we use $B(\xi_0,r) := \{ \xi \in \R^3: |\xi-\xi_0| < r \}$ to denote the open ball of radius $r$ centred at $\xi_0$. Given a subset $B$ of $\R^3$ and a real number $\lambda$, we use $\lambda \cdot B := \{ \lambda \xi: \xi \in B \}$ to denote the dilate of $B$ by $\lambda$. If $P$ is a mathematical statement, we use $1_P$ to denote the quantity $1$ when $P$ is true and $0$ when $P$ is false. Given two real vector spaces $V,W$, we define the tensor product $V \otimes W$ to be the real vector space spanned by formal tensor products $v \otimes w$ with $v \in V$ and $w \in W$, subject to the requirement that the map $(v,w) \mapsto v \otimes w$ is bilinear. Thus for instance $V \otimes \C$ is the complexification of $V$, that is to say the space of formal linear combinations $v_1+iv_2$ with $v_1,v_2 \in V$. Let $\epsilon_0 > 0$ be fixed; we allow all implied constants in the $O()$ notation to depend on $\epsilon_0$. ... The reader may wish to keep in mind the hierarchy of parameters $1 \ll \frac{1}{\epsilon_0} \ll K \ll \frac{1}{\eps} \ll n_0$ as a heuristic for comparing the magnitude of various quantities appearing in the sequel.

**Global Definitions:**
the Sobolev space $H^{10}_\df(\R^3)$ of (distributional) vector fields $u: \R^3 \to \R^3$ with $H^{10}$ regularity (thus the weak derivatives $\nabla^j u$ are square-integrable for $j=0,\dots,10$) and which are divergence free in the distributional sense: $\nabla \cdot u = 0$. the $L^2$ inner product\footnote{We will not use the $H^{10}_\df$ inner product in this paper, thus all appearances of the $\langle,\rangle$ notation should be interpreted in the $L^2$ sense.} $$ \langle u, v \rangle := \int_{\R^3} u \cdot v\ dx$$ on vector fields $u, v: \R^3\to \R^3$. the \emph{Euler bilinear operator} $B: H^{10}_\df(\R^3) \times H^{10}_\df(\R^3) \to H^{10}_\df(\R^3)^*$ via duality as $$ \langle B(u,v), w \rangle := -\frac{1}{2} \int_{\R^3} \left(\left(\left(u \cdot \nabla\right) v\right) \cdot w\right) + \left(\left(\left(v \cdot \nabla\right) u\right) \cdot w\right)\ dx$$ for $u,v,w \in H^{10}_\df(\R^3)$; it is easy to see from Sobolev embedding that this operator is well defined. More directly, we can write $$ B(u,v) = -\frac{1}{2} P \left[ (u \cdot \nabla) v + (v \cdot \nabla) u \right]$$ where $P$ is the \emph{Leray projection} onto divergence-free vector fields, defined on square-integrable $u: \R^3 \to \R^3$ by the formula $$ Pu_i := u_i - \Delta^{-1} \partial_i \partial_j u_j$$ with the usual summation conventions, where $\Delta^{-1} \partial_i \partial_j$ is defined as the Fourier multiplier with symbol $\frac{\xi_i \xi_j}{|\xi|^2}$. We refer to the form $(u,v,w) \mapsto\langle B(u,v),w \rangle$ as the \emph{Euler trilinear form}. Given a Schwartz divergence-free vector field $u_0: \R^3 \to \R^3$ and a time interval $I \subset [0,+\infty)$ containing $0$, we define a \emph{mild $H^{10}$ solution to the Navier-Stokes equations} (or \emph{mild solution} for short) with initial data $u_0$ to be a continuous map $u: I \to H^{10}_\df(\R^3)$ obeying the integral equation $$ u(t) = e^{t\Delta} u_0 + \int_0^t e^{(t-t')\Delta} B(u(t'),u(t'))\ dt'$$ for all $t \in I$. a (complex) \emph{Fourier multiplier of order $0$} to be an operator $m(D)$ defined on (the complexification $H^{10}_\df(\R^3) \otimes \C$ of) $H^{10}_\df(\R^3)$ by the formula $$ \widehat{m(D) u}(\xi) := m(\xi) \hat u(\xi)$$ where $m: \R^3 \to \C$ is a function that is smooth away from the origin, with the seminorms $$ \| m \|_k := \sup_{\xi \neq 0} |\xi|^k |\nabla^k m(\xi)|$$ being finite for every natural number $k$. We say that $m(D)$ is \emph{real} if the symbol $m$ obeys the symmetry $m(-\xi) = \overline{m(\xi)}$ for all $\xi \in \R^3 \backslash \{0\}$. the \emph{dilation operators} $$ \Dil_\lambda(u)(x) := \lambda^{3/2} u(\lambda x)$$ for $\lambda > 0$. an \emph{averaged Euler bilinear operator} to be an operator $\tilde B: H^{10}_\df(\R^3) \times H^{10}_\df(\R^3) \to H^{10}_\df(\R^3)^*$, defined via duality by the formula $$ \langle \tilde B(u,v), w \rangle := \E \left\langle B\left( m_1(D) \Rot_{R_1} \Dil_{\lambda_1} u, m_2(D) \Rot_{R_2} \Dil_{\lambda_2} v\right), m_3(D) \Rot_{R_3} \Dil_{\lambda_3} w\right\rangle$$ for all $u,v,w \in H^{10}_\df(\R^3)$, where $m_1(D),m_2(D),m_3(D)$ are random real Fourier multipliers of order $0$, $R_1,R_2,R_3$ are random rotations, and $\lambda_1,\lambda_2,\lambda_3$ are random dilations, obeying the moment bounds $$ \E \| m_1 \|_{k_1} \|m_2 \|_{k_2} \|m_3\|_{k_3} < \infty$$ and $$ C^{-1} \leq \lambda_1,\lambda_2,\lambda_3 \leq C$$ almost surely for any natural numbers $k_1,k_2,k_3$ and some finite $C$. A \emph{basic local cascade operator} (with dyadic scale parameter $\epsilon_0>0$) is a bilinear operator $C: H^{10}_\df(\R^3) \times H^{10}_\df(\R^3) \to H^{10}_\df(\R^3)^*$ defined via duality by the formula $$ \langle C(u,v), w \rangle = \sum_{n \in \Z} (1+\epsilon_0)^{5n/2} \langle u, \psi_{1,n} \rangle \langle v, \psi_{2,n} \rangle \langle w, \psi_{3,n} \rangle$$ for all $u,v,w \in H^{10}_\df(\R^3)$, where for $i=1,2,3$ and $n \in \Z$, $\psi_{i,n}: \R^3 \to \R^3$ is the $L^2$-rescaled function $$ \psi_{i,n}(x) := (1+\epsilon_0)^{3n/2} \psi_i\left( (1+\epsilon_0)^n x \right)$$ and $\psi_i: \R^3 \to \R^3$ is a Schwartz function whose Fourier transform is supported on the annulus $\{ \xi: 1-2\epsilon_0 \leq |\xi| \leq 1+2\epsilon_0 \}$. A \emph{local cascade operator} is defined to be a finite linear combination of basic local cascade operators. Let $C, C': H^{10}_\df(\R^3) \otimes \C \times H^{10}_\df(\R^3) \otimes \C \to H^{10}_\df(\R^3)^* \otimes \C$ be bounded (complex-)bilinear operators. We say that $C$ is a \emph{complex average} of $C'$ if there exists a finite measure space $(\Omega,\mu)$ and measurable functions $m_{i,\cdot}(D): \Omega \to {\mathcal M}_0 \otimes \C$, $R_{i,\cdot}: \Omega \to \SO(3)$, $\lambda_{i,\cdot}: \Omega \to (0,+\infty)$ for $i=1,2,3$ such that $$ \langle C(u,v), w \rangle = \int_\Omega \left\langle C'\left( m_{1,\omega}(D) \Rot_{R_{1,\omega}} \Dil_{\lambda_{1,\omega}} u, m_{2,\omega}(D) \Rot_{R_{2,\omega}} \Dil_{\lambda_{2,\omega}} v\right), m_{3,\omega}(D) \Rot_{R_{3,\omega}} \Dil_{\lambda_{3,\omega}} w\right\rangle\ d\mu(\omega),$$ and that one has the integrability conditions $$ \int_\Omega \| m_{1,\omega}(D) \|_{k_1} \| m_{2,\omega}(D) \|_{k_2} \| m_{3,\omega}(D) \|_{k_3}\ d\mu(\omega) < \infty$$ and $$ C_0^{-1} \leq \lambda_1(\omega), \lambda_2(\omega), \lambda_3(\omega) \leq C_0$$ almost surely for any natural numbers $k_1,k_2,k_3$ (recall that the seminorms $\| \|_k$ on ${\mathcal M}_0 \otimes \C$ were defined in \eqref{seminorm}) and some finite $C_0$. Here, we complexify the inner product $\langle,\rangle$ by defining $$ \langle u, v \rangle := \int_{\R^3} u(x) \cdot v(x)\ dx$$ for complex vector fields $u,v \in H^{10}_\df(\R^3) \otimes \C$; note that we do \emph{not} place a complex conjugate on the $v$ factor, so the inner product is complex bilinear rather than sesquilinear.

**Global Assumptions:**
By applying the rescaling $\tilde u(t,x) := \nu u( \nu t, x )$, $\tilde p(t,x) := \nu p( \nu t, \nu x)$ we may normalise $\nu=1$ (note that there is no smallness requirement on the initial data $u_0$), and we shall do so henceforth. Let $\epsilon_0 > 0$ be fixed; we allow all implied constants in the $O()$ notation to depend on $\epsilon_0$. As in the previous section, we need a large constant $K \geq 1$, which we assume to be sufficiently large depending on $\epsilon_0$, and then a small constant $0 < \eps < 1$, which we assume to be sufficiently small depending on both $K$ and $\epsilon_0$. Finally, we take $n_0$ sufficiently large depending on $\epsilon_0, K, \eps$.

**Theorem:**
Finite time blowup for an averaged Navier-Stokes equation]\label{main}  There exists a symmetric averaged Euler bilinear operator $\tilde B: H^{10}_\df(\R^3) \times H^{10}_\df(\R^3) \to H^{10}_\df(\R^3)^*$ obeying the cancellation property \eqref{cancellation-2} for all $u \in H^{10}_\df(\R^3)$, and a Schwartz divergence-free vector field $u_0$, such that there is no global-in-time mild solution $u: [0,+\infty) \to H^{10}_\df(\R^3)$ to the averaged Navier-Stokes equation \eqref{ns-modified} with initial data $u_0$.
"""

emb = model.encode(tao_theorem, convert_to_tensor=True)
util.cos_sim(emb, query_emb)