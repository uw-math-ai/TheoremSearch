"""
Stream (primary_category, embedding) rows from Postgres using psycopg2 + pgvector,
fit a 2D PCA with IncrementalPCA, and plot a stratified sample.

Requirements:
  pip install psycopg2-binary pgvector scikit-learn matplotlib numpy boto3
"""

import os
import json
import boto3
import numpy as np
import psycopg2
from psycopg2.extensions import connection
from pgvector.psycopg2 import register_vector
from sklearn.decomposition import IncrementalPCA
import matplotlib.pyplot as plt
from ec2.rds.connect import get_rds_connection
# ============================================================
# CONFIG
# ============================================================
BATCH_SIZE = 5000
PCA_COMPONENTS = 2
MAX_PER_CATEGORY = 15000
RANDOM_SEED = 42

# If paper.categories is not text[], change ::text[] to ::varchar[] (or remove cast).
SQL = """
SELECT
  p.primary_category,
  teq.embedding,
  (p.categories @> ARRAY['math.AG','math.PR']::text[]) AS is_both_ag_nt
FROM paper AS p
JOIN theorem AS t
  ON t.paper_id = p.paper_id
JOIN theorem_slogan AS ts
  ON ts.theorem_id = t.theorem_id
JOIN theorem_embedding_qwen AS teq
  ON teq.slogan_id = ts.slogan_id
WHERE teq.embedding IS NOT NULL
  AND p.primary_category IN ('math.AG', 'math.PR');
"""


# ============================================================
# STREAMING GENERATOR
# ============================================================
def stream_joined_embeddings(conn, batch_size=BATCH_SIZE):
    """
    Yields:
      X_batch: (B, d) float32 numpy array
      cats:    (B,) object numpy array (primary_category)
      both:    (B,) bool numpy array (paper is cross-listed AG+PR)
    """
    cur = conn.cursor(name="theorem_stream")  # server-side cursor
    cur.itersize = batch_size
    cur.execute(SQL)

    while True:
        rows = cur.fetchmany(batch_size)
        if not rows:
            break

        cats = np.array([r[0] for r in rows], dtype=object)
        X = np.vstack([np.asarray(r[1], dtype=np.float32) for r in rows])
        both = np.array([bool(r[2]) for r in rows], dtype=bool)

        yield X, cats, both

    cur.close()


# ============================================================
# SIMPLE GROUP-CAPPED SAMPLER (keeps plotting readable)
#   Groups:
#     - "AG only"
#     - "PR only"
#     - "AG & PR (cross-listed)"
# ============================================================
class GroupCapSampler:
    def __init__(self, max_per_group=None, seed=RANDOM_SEED):
        self.max_per_group = max_per_group
        self.rng = np.random.default_rng(seed)
        self.seen = {"AG only": 0, "PR only": 0, "AG & PR": 0}
        self.keep = {"AG only": [], "PR only": [], "AG & PR": []}

    def _group(self, primary_cat: str, both: bool) -> str:
        if both:
            return "AG & PR"
        if primary_cat == "math.AG":
            return "AG only"
        return "PR only"

    def add_batch(self, Z, cats, both_flags):
        for z, cat, both in zip(Z, cats, both_flags):
            g = self._group(str(cat), bool(both))
            self.seen[g] += 1

            if self.max_per_group is None:
                self.keep[g].append(z.astype(np.float32, copy=False))
                continue

            bucket = self.keep[g]
            if len(bucket) < self.max_per_group:
                bucket.append(z.astype(np.float32, copy=False))
            else:
                # reservoir replacement (keeps an unbiased sample per group)
                p = self.max_per_group / self.seen[g]
                if self.rng.random() < p:
                    j = self.rng.integers(0, self.max_per_group)
                    bucket[j] = z.astype(np.float32, copy=False)

    def get_arrays(self):
        out = {}
        for g, pts in self.keep.items():
            out[g] = np.vstack(pts) if pts else np.empty((0, 2), dtype=np.float32)
        return out


# ============================================================
# MAIN
# ============================================================
def main():
    conn = get_rds_connection()
    try:
        register_vector(conn)

        # -------------------------
        # PASS 1: FIT PCA
        # -------------------------
        ipca = IncrementalPCA(n_components=PCA_COMPONENTS, batch_size=BATCH_SIZE)

        total = 0
        d_dim = None
        for X_batch, _cats, _both in stream_joined_embeddings(conn, batch_size=BATCH_SIZE):
            if d_dim is None:
                d_dim = X_batch.shape[1]
                print(f"Detected embedding dimension: {d_dim}")
            ipca.partial_fit(X_batch)
            total += X_batch.shape[0]
            if total % (BATCH_SIZE * 20) == 0:
                print(f"Fitting PCA: {total} rows processed")

        print(f"PCA fit complete on {total} rows.")
        print("Explained variance ratio:", ipca.explained_variance_ratio_)

        # -------------------------
        # PASS 2: TRANSFORM + SAMPLE FOR PLOTTING
        # -------------------------
        sampler = GroupCapSampler(max_per_group=MAX_PER_CATEGORY, seed=RANDOM_SEED)

        total2 = 0
        for X_batch, cats, both_flags in stream_joined_embeddings(conn, batch_size=BATCH_SIZE):
            Z = ipca.transform(X_batch)  # (B, 2)
            sampler.add_batch(Z, cats, both_flags)
            total2 += X_batch.shape[0]
            if total2 % (BATCH_SIZE * 20) == 0:
                print(f"Transforming: {total2} rows processed")

        groups = sampler.get_arrays()
        for g, arr in groups.items():
            print(f"{g}: plotting {arr.shape[0]} points (seen {sampler.seen[g]})")

    finally:
        conn.close()

    # -------------------------
    # PLOT
    # -------------------------
    plt.figure(figsize=(7, 7), dpi=100)

    # Plot order matters: draw non-crosslisted first, then crosslisted on top
    if groups["AG only"].shape[0] > 0:
        plt.scatter(groups["AG only"][:, 0], groups["AG only"][:, 1], s=6, alpha=0.35, label="AG only")
    if groups["PR only"].shape[0] > 0:
        plt.scatter(groups["PR only"][:, 0], groups["PR only"][:, 1], s=6, alpha=0.35, label="PR only")
    if groups["AG & PR"].shape[0] > 0:
        plt.scatter(groups["AG & PR"][:, 0], groups["AG & PR"][:, 1], s=25, alpha=0.85, label="AG & PR (cross-listed)")

    plt.xlabel("PC1")
    plt.ylabel("PC2")
    plt.title("PCA of theorem embeddings: math.AG vs math.PR, cross-listed highlighted")
    plt.legend(markerscale=2)
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()