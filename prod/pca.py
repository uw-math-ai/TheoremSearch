import numpy as np
import matplotlib.pyplot as plt
import umap
from dotenv import load_dotenv
from sklearn.decomposition import PCA

from rds import get_rds_connection

load_dotenv()

TOP_10 = [
    'math.AP','math.CO','math.AG','math.PR','math.NT',
    'math.DG','math.DS','math.FA','math.RT','math.GR'
]

PER_CAT = 1000
RANDOM_STATE = 42

SQL = """SELECT
  s.theorem_id,
  s.primary_category,
  r.embedding AS raw_embedding,
  g.embedding AS slogan_embedding
FROM arxiv_umap_sample s
JOIN raw_theorem_embedding_gemma r
  ON r.theorem_id = s.theorem_id
JOIN theorem_slogan ts
  ON ts.theorem_id = s.theorem_id
JOIN theorem_embedding_gemma g
  ON g.slogan_id = ts.slogan_id;"""


def l2_normalize(X, eps=1e-12):
    return X / np.maximum(np.linalg.norm(X, axis=1, keepdims=True), eps)


def main():
    conn = get_rds_connection()
    cur = conn.cursor()

    cur.execute(SQL, {"cats": TOP_10, "per_cat": PER_CAT})
    rows = cur.fetchall()

    cur.close()
    conn.close()

    cats = np.array([r[1] for r in rows])
    X_raw = np.array([r[2] for r in rows], dtype=np.float32)
    X_slogan = np.array([r[3] for r in rows], dtype=np.float32)

    # Normalize
    X_raw = l2_normalize(X_raw)
    X_slogan = l2_normalize(X_slogan)

    # Fit projection
    X_all = np.vstack([X_raw, X_slogan])

    # PCA
    pca = PCA(n_components=50, random_state=RANDOM_STATE)
    X_all_pca = pca.fit_transform(X_all)

    reducer = umap.UMAP(
        n_neighbors=30,
        min_dist=0.1,
        n_components=2,
        metric="cosine",
        random_state=RANDOM_STATE
    )

    Z_all = reducer.fit_transform(X_all_pca)

    Z_raw = Z_all[:len(X_raw)]
    Z_slogan = Z_all[len(X_raw):]

    # Plot
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharex=True, sharey=True)

    for cat in TOP_10:
        mask = cats == cat
        axes[0].scatter(Z_raw[mask, 0], Z_raw[mask, 1],
                        s=6, alpha=0.7, label=cat)
        axes[1].scatter(Z_slogan[mask, 0], Z_slogan[mask, 1],
                        s=6, alpha=0.7, label=cat)

    axes[0].set_title("Raw theorem embeddings")
    axes[1].set_title("Slogan (natural-language) embeddings")

    for ax in axes:
        ax.set_xlabel("UMAP-1")
        ax.set_ylabel("UMAP-2")

    axes[1].legend(
        loc="center left",
        bbox_to_anchor=(1.02, 0.5),
        fontsize=8,
        markerscale=2
    )

    plt.suptitle(
        "UMAP comparison: effect of natural-language rewriting on category separability",
        fontsize=14
    )

    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
