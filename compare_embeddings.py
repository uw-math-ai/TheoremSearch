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

# %%
# --- 2. Define the evaluation metrics ---
import numpy as np
from sentence_transformers import util

# ---------- helpers: qrels ----------
# qrels can be:
#   {q_idx: [doc_idx, ...]}                 -> binary relevance (1)
#   {q_idx: {doc_idx: grade, ...}}          -> graded relevance (0..3)
# ---------- ranking ----------
def rank_concepts(sim_matrix):
    """
    sim_matrix: (num_queries, num_docs)
    returns: list of arrays, each is doc indices sorted by descending score
    """
    return [np.argsort(-row) for row in sim_matrix]

# ---------- metrics ----------
def evaluate_retrieval(model, theorems, queries, qrels, top_k_report=3):
    # encode
    print("Encoding...")
    s_emb = model.encode([item[0] for item in theorems], convert_to_tensor=True)
    q_emb = model.encode([item[0] for item in queries], convert_to_tensor=True)
    print("Creating sim_matrix...")
    sim_matrix = util.cos_sim(q_emb, s_emb).cpu().numpy()

    print("Cos-sim matrix dim", sim_matrix.shape)

    print("Ranking concepts...")
    # ranked = rank_concepts(sim_matrix)

    print("="*50)
    print("Binary metrics")
    bin_metrics = {
        f"P@1": precision_at_k,
        f"H@{top_k_report}": hit_at_k,
        f"MRR@{top_k_report}": mrr_at_k,
    }

    for item in bin_metrics:
        
        res = bin_metrics[item](sim_matrix, qrels, k=(1 if item[0] == "P" else top_k_report))
        print(f"{item} | {res}")

    print("="*50)
    print("Graded metrics")
    grad_metrics = {
        f"nDCG@{top_k_report}": ndcg_at_k,
        f"ERR@{top_k_report}": err_at_k,
        f"Q-measure@{top_k_report}": q_measure_at_k,
    }

    for item in grad_metrics:
        
        res = grad_metrics[item](sim_matrix, qrels, k=top_k_report)
        print(f"{item} | {res}")


def precision_at_k(sim_matrix, qrels, k=5):
    """
    Computes mean Precision@k when the i-th query corresponds
    to the i-th correct document.

    sim_matrix: numpy array (num_queries, num_docs)
                similarity scores
    k: cutoff
    """
    # rank docs for each query
    ranked_docs = np.argsort(-sim_matrix, axis=1)

    precisions = []
    num_queries = sim_matrix.shape[0]

    for q in range(num_queries):
        correct_doc = next(k for k, v in qrels[q].items() if v == 1) # q
        top_k = ranked_docs[q, :k]

        hit = 1 if correct_doc in top_k else 0
        precisions.append(hit / k)

    return float(np.mean(precisions))


def hit_at_k(sim_matrix, qrels, k=5):
    """
    Computes mean Hit@k when the i-th query corresponds
    to the i-th correct document.

    sim_matrix: numpy array (num_queries, num_docs)
                similarity scores
    k: cutoff
    """
    ranked_docs = np.argsort(-sim_matrix, axis=1)

    hits = []
    num_queries = sim_matrix.shape[0]

    for q in range(num_queries):
        correct_doc = next(k for k, v in qrels[q].items() if v == 1) # q
        top_k = ranked_docs[q, :k]
        hit = 1.0 if correct_doc in top_k else 0.0
        hits.append(hit)

    return float(np.mean(hits))


def mrr_at_k(sim_matrix, qrels, k=None):
    """
    Computes Mean Reciprocal Rank (MRR@k) when the i-th query
    corresponds to the i-th correct document.

    sim_matrix: numpy array (num_queries, num_docs)
                similarity scores
    k: optional cutoff (if None, use all docs)
    """
    ranked_docs = np.argsort(-sim_matrix, axis=1)

    rrs = []
    num_queries = sim_matrix.shape[0]

    for q in range(num_queries):
        correct_doc = next(k for k, v in qrels[q].items() if v == 1) # q
        row = ranked_docs[q]

        if k is not None:
            row = row[:k]

        # find index of correct_doc in the ranked list, if present
        matches = np.where(row == correct_doc)[0]

        if matches.size > 0:
            rank = int(matches[0]) + 1  # convert 0-based to 1-based
            rrs.append(1.0 / rank)
        else:
            rrs.append(0.0)

    return float(np.mean(rrs))

def _generate_qrels(queries, slogans):
    qrels = {}
    for i in range(len(queries)):
        idx = queries[i][1]
        qrels[i] = {j: 0.5 if slogans[j][1] == idx else 0 for j in range(len(slogans))}
        # qrels[i][i] = 1

    return qrels


def _get_rels_for_query(order, rels_dict, k=None, default=0.0):
    """
    order: np.ndarray of doc_ids in ranked order for one query
    rels_dict: dict {doc_id: relevance_score}
    k: optional cutoff
    """
    if k is not None:
        order = order[:k]
    return np.array([rels_dict.get(d, default) for d in order], dtype=float)


def _dcg_from_rels(rels, gain="exp"):
    """
    rels: 1D np array of relevance scores in ranked order
    gain: "exp" for 2^rel - 1, "linear" for rel
    """
    if rels.size == 0:
        print("TOO SMALL")
        return 0.0

    if gain == "exp":
        gains = np.power(2.0, rels) - 1.0
    elif gain == "linear":
        gains = rels
    else:
        raise ValueError(f"Unknown gain scheme: {gain}")

    discounts = 1.0 / np.log2(np.arange(2, rels.size + 2))
    return float(np.sum(gains * discounts))


def ndcg_at_k(ranked, qrels, k=10, gain="exp"):
    """
    ranked: list of np.ndarrays; ranked[q] = doc_ids sorted by score
    qrels: {q: {doc_id: relevance_score}}
    """
    ndcgs = []

    ranked = np.argsort(-ranked, axis=1)

    for q, order in enumerate(ranked):
        rels_dict = qrels.get(q, {})
        rels = _get_rels_for_query(order, rels_dict, k)

        dcg = _dcg_from_rels(rels, gain=gain)

        # ideal: sort relevance scores desc
        ideal_rels = np.sort(np.array(list(rels_dict.values()), dtype=float))[::-1]
        if k is not None:
            ideal_rels = ideal_rels[:k]

        idcg = _dcg_from_rels(ideal_rels, gain=gain)

        if idcg == 0.0:
            ndcgs.append(0.0)
        else:
            ndcgs.append(dcg / idcg)

    return float(np.mean(ndcgs))


def _get_rels_sparse(order, rels_dict, k=None, default=0.0):
    """
    order: 1D array of doc indices (ranked[q])
    rels_dict: {doc_id: relevance_score} for this query
    k: cutoff
    """
    if k is not None:
        order = order[:k]
    return np.array([rels_dict.get(int(d), default) for d in order], dtype=float)


def err_at_k(ranked, qrels, k=10, max_rel=None):
    """
    ranked: 2D np.ndarray or list of 1D arrays
        ranked[q] is doc indices sorted by descending score.
    qrels: dict[int -> dict[int -> float]]
        qrels[q][d] = relevance score of doc d for query q.
    k: int
        Cutoff rank.
    max_rel: float or None
        Maximum possible relevance grade R. If None, inferred from qrels.
    """
    ranked = np.argsort(-ranked, axis=1)

    # ----- infer max_rel if needed -----
    if max_rel is None:
        max_rel = 0.0
        for rels_dict in qrels.values():
            if rels_dict:
                max_rel = max(max_rel, max(rels_dict.values()))
        if max_rel <= 0.0:
            return 0.0  # no relevance at all

    denom = 2.0 ** max_rel  # 2^R

    errs = []

    for q, order in enumerate(ranked):
        rels_dict = qrels.get(q, None)
        if not rels_dict:       # None or empty dict
            errs.append(0.0)
            continue

        rels = _get_rels_sparse(order, rels_dict, k=k)
        if rels.size == 0:
            errs.append(0.0)
            continue

        # rel -> satisfaction probability p_i
        ps = (np.power(2.0, rels) - 1.0) / denom

        err_q = 0.0
        prob_not_sat = 1.0

        for i, p in enumerate(ps, start=1):
            if p <= 0.0:
                prob_not_sat *= (1.0 - p)
                continue
            err_q += prob_not_sat * p * (1.0 / i)
            prob_not_sat *= (1.0 - p)
            if prob_not_sat <= 1e-12:
                break

        errs.append(err_q)

    return float(np.mean(errs)) if errs else 0.0



def q_measure_at_k(ranked, qrels, k=10, max_rel=None):
    """
    ranked: 2D np.ndarray or list of 1D arrays
        ranked[q] is doc indices sorted by descending score.
    qrels: dict[int -> dict[int -> float]]
        qrels[q][d] = relevance score of doc d for query q.
    k: int
        Cutoff rank.
    max_rel: float or None
        Maximum possible relevance grade R. If None, inferred from qrels.
    """

    ranked = np.argsort(-ranked, axis=1)

    # infer max_rel if needed
    if max_rel is None:
        max_rel = 0.0
        for rels_dict in qrels.values():
            if rels_dict:
                max_rel = max(max_rel, max(rels_dict.values()))
        if max_rel <= 0.0:
            return 0.0

    denom = 2.0 ** max_rel  # 2^R
    scores = []

    for q, order in enumerate(ranked):
        rels_dict = qrels.get(q, None)
        if not rels_dict:
            scores.append(0.0)
            continue

        # all relevance values (for ideal total gain CG*)
        rel_values = np.array(list(rels_dict.values()), dtype=float)
        gains_all = (np.power(2.0, rel_values) - 1.0) / denom
        CG_star = gains_all.sum()
        if CG_star <= 0.0:
            scores.append(0.0)
            continue

        # gains for retrieved docs in top-k
        rels_k = _get_rels_sparse(order, rels_dict, k=k)
        gains_k = (np.power(2.0, rels_k) - 1.0) / denom

        CG = 0.0
        q_sum = 0.0

        for i, g in enumerate(gains_k, start=1):
            if g <= 0.0:
                continue
            CG += g
            precision_i = CG / i
            q_sum += g * precision_i

        scores.append(q_sum / CG_star)

    return float(np.mean(scores)) if scores else 0.0



#%%
# collect theorem slogans from rds and update validation set

import dotenv
import pandas as pd
import re
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

    paper_like = '%' + str(row['paper_id']) + '%'
    theorem_name = str(row['theorem'])
    query_1 = """
    SELECT theorem_id, body
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
            rows_raw2 = cur.fetchall()
        validation_set.loc[idx, context_window] = rows_raw2[0][0]
        validation_set.loc[idx, "body"] = re.sub(r"\s+", " ", rows_raw[0][1])
    except:
        print(f"theorem info not found for: {row['paper_id'], row['theorem']}")
        continue

print(validation_set[validation_set[context_window].notnull()])

validation_set.to_csv('validation_set.csv')


#%%
# --- 3. Evaluate performance ---
# select context window to test
context_window = "body-and-summary-v1"

vals = pd.read_csv("validation_set.csv", header=0, index_col=0, dtype={"paper_id": str})
slogans = pd.read_csv("full_slogan_set.csv", header=0, index_col=0, dtype={"paper_id": str})
vals = vals[vals[context_window].notnull()]

qrels_array = []
# identify correct documents from full validation set
for idx, row in vals.iterrows():
    indices = slogans[(slogans["theorem"] == row[1]) & (slogans["paper_id"] == row[3])].index
    qrels_array.append((idx, int(indices[0])))

queries = list(zip(vals['query'], vals["paper_id"]))
theorem_slogans = list(zip(slogans[context_window], slogans["paper_id"]))

qrels_table = _generate_qrels(queries, theorem_slogans)

# add correct documents into qrels table
for i in range(len(qrels_array)):
    qrels_table[i][qrels_array[i][1]]

grading_metric = {
    "Exact Match": 1,
    "Paper Match": 0.5,
    "No Match": 0
}

print("Number of theorems testing: ", len(vals))
print("Context window: ", context_window)

# Choose the embedder
# model_name = "google/embeddinggemma-300m" 
# model_name = "Qwen/Qwen3-Embedding-0.6B"
# model_name = "math-similarity/Bert-MLM_arXiv-MP-class_zbMath"
model_name = "Qwen/Qwen3-Embedding-0.6B" # Qwen3 0.6B is the best of three embedders
model = load_model(model_name)
print("Model name: ", model_name)

evaluate_retrieval(model, theorem_slogans, queries, qrels_table, 5)
# %%
# --- Create full query set ---
import dotenv
import pandas as pd
import re
from ec2.rds.paginate import paginate_query
from ec2.rds.connect import get_rds_connection

df = pd.DataFrame({
    "paper_id": pd.Series(dtype="string"),
    "theorem": pd.Series(dtype="string"),
    "body-only-v1": pd.Series(dtype="string"),
    "body-and-summary-v1": pd.Series(dtype="string"),
})

dotenv.load_dotenv()
conn = get_rds_connection()

query_1 = """
WITH good_table AS (
    SELECT
        pap.authors,
        LEFT(theo.paper_id, LENGTH(theo.paper_id) - 2) AS paper_id,
        theo.name,
        slo.theorem_id,
        slo.model,
        slo.prompt_id,
        slo.slogan
    FROM theorem_slogan AS slo
    LEFT JOIN theorem AS theo
      ON theo.theorem_id = slo.theorem_id
    LEFT JOIN paper AS pap
      ON theo.paper_id = pap.paper_id
    WHERE pap.authors && ARRAY[
        'Giovanni Inchiostro', 
        'Jarod Alper', 
        'Dori Bejleri',
        'Roberto Svaldi',
        'Valery Alexeev',
        'Vistoli Angelo',
        'Michele Pernice',
        'János Kollár'
    ]
)
SELECT
        paper_id,
        name,
        MAX(slogan) FILTER (WHERE prompt_id = 'body-only-v1') AS body_only_v1,
        MAX(slogan) FILTER (WHERE prompt_id = 'body-and-summary-v1') AS body_and_summary_v1
    FROM good_table
    GROUP BY paper_id, name;
"""
try:
    with conn.cursor() as cur:
        cur.execute(query_1, None)
        cols = [d[0] for d in cur.description]
        rows_raw = cur.fetchall()

        for row in rows_raw:
            df.loc[len(df)] = row

        df.to_csv("full_slogan_set.csv")

except Exception as e:
    print(f"found exception {e}")

# %%
