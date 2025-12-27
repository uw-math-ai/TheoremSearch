# %%
# Figure 1 (Plot of all arXiv math tags with cluster means and their distances)
import os
import json
import boto3
import numpy as np
import psycopg2
from psycopg2.extensions import connection
from pgvector.psycopg2 import register_vector
from sklearn.decomposition import IncrementalPCA
import matplotlib.pyplot as plt
from adjustText import adjust_text


# ============================================================
# EXISTING CONNECTION METHOD (UNCHANGED)
# ============================================================
def get_rds_connection() -> connection:
    region = os.getenv("AWS_REGION", "us-west-2")
    secret_arn = os.getenv("RDS_SECRET_ARN")
    host = os.getenv("RDS_HOST", "")
    dbname = "postgres"

    sm = boto3.client("secretsmanager", region_name=region)
    secret_value = sm.get_secret_value(SecretId=secret_arn)
    secret_dict = json.loads(secret_value["SecretString"])

    conn = psycopg2.connect(
        host=host or secret_dict.get("host"),
        port=int(secret_dict.get("port", 5432)),
        dbname=dbname or secret_dict.get("dbname", "postgres"),
        user=secret_dict["username"],
        password=secret_dict["password"],
        sslmode="require",
    )
    return conn


# ============================================================
# CONFIG
# ============================================================
BATCH_SIZE = 5000
PCA_COMPONENTS = 2
MAX_PER_CATEGORY = 25000
RANDOM_SEED = 42

# Plot options
POINT_ALPHA = 0.08          # low alpha for individual points
POINT_SIZE = 6
MEAN_POINT_SIZE = 80        # cluster mean marker size
MEAN_ALPHA = 1.0            # full opacity for means
ANNOTATE_MEANS = True       # label means with category text
TOPK_DISTANCES = 30         # print top-k closest mean pairs

SQL = """
SELECT
  p.primary_category,
  teq.embedding
FROM paper AS p
JOIN theorem AS t
  ON t.paper_id = p.paper_id
JOIN theorem_slogan AS ts
  ON ts.theorem_id = t.theorem_id
JOIN theorem_embedding_qwen AS teq
  ON teq.slogan_id = ts.slogan_id
WHERE teq.embedding IS NOT NULL
  AND p.primary_category IS NOT NULL
  AND p.primary_category LIKE 'math.%';
"""


# ============================================================
# STREAMING GENERATOR (SERVER-SIDE CURSOR)
# ============================================================
def stream_joined_embeddings(conn, batch_size=BATCH_SIZE):
    cur = conn.cursor(name="theorem_stream")  # server-side cursor
    cur.itersize = batch_size
    cur.execute(SQL)

    while True:
        rows = cur.fetchmany(batch_size)
        if not rows:
            break

        cats = np.array([r[0] for r in rows], dtype=object)
        X = np.vstack([np.asarray(r[1], dtype=np.float32) for r in rows])
        yield X, cats

    cur.close()


# ============================================================
# STRATIFIED SAMPLER (FOR PLOTTING)
# ============================================================
class StratifiedReservoir:
    def __init__(self, max_per_category, seed=RANDOM_SEED):
        self.max_per_category = max_per_category
        self.rng = np.random.default_rng(seed)
        self.seen = {}
        self.data = {}

    def add_batch(self, Z, cats):
        for z, cat in zip(Z, cats):
            cat = str(cat)
            self.seen[cat] = self.seen.get(cat, 0) + 1
            bucket = self.data.setdefault(cat, [])

            if len(bucket) < self.max_per_category:
                bucket.append(z)
            else:
                # reservoir replacement
                p = self.max_per_category / self.seen[cat]
                if self.rng.random() < p:
                    j = self.rng.integers(0, self.max_per_category)
                    bucket[j] = z

    def to_arrays(self):
        Z_all = []
        cats_all = []
        for cat, pts in self.data.items():
            if pts:
                Z_all.append(np.vstack(pts))
                cats_all.extend([cat] * len(pts))
        return (
            np.vstack(Z_all) if Z_all else np.empty((0, 2)),
            np.array(cats_all, dtype=object),
        )


# ============================================================
# MEAN ACCUMULATOR (RUNNING SUMS/COUNTS)
# ============================================================
class MeanAccumulator:
    """
    Online mean for each category in PCA-space (2D).
    Stores sum vectors and counts so memory stays tiny.
    """
    def __init__(self):
        self.sum = {}    # cat -> np.array([sx, sy])
        self.count = {}  # cat -> int

    def add_batch(self, Z, cats):
        for z, cat in zip(Z, cats):
            cat = str(cat)
            if cat not in self.sum:
                self.sum[cat] = np.zeros((Z.shape[1],), dtype=np.float64)
                self.count[cat] = 0
            self.sum[cat] += z.astype(np.float64, copy=False)
            self.count[cat] += 1

    def means(self):
        cats = sorted(self.sum.keys())
        M = np.vstack([self.sum[c] / self.count[c] for c in cats]).astype(np.float32)
        counts = np.array([self.count[c] for c in cats], dtype=np.int64)
        return cats, M, counts


def pairwise_distances(M):
    """
    Euclidean distance matrix for mean points M (n, 2).
    Returns D (n, n).
    """
    # D_ij = ||M_i - M_j||
    diff = M[:, None, :] - M[None, :, :]
    D = np.sqrt((diff ** 2).sum(axis=2))
    return D


# ============================================================
# MAIN
# ============================================================
def main():
    np.random.seed(RANDOM_SEED)

    conn = get_rds_connection()
    try:
        register_vector(conn)

        # -------------------------
        # PASS 1: FIT PCA
        # -------------------------
        ipca = IncrementalPCA(
            n_components=PCA_COMPONENTS,
            batch_size=BATCH_SIZE,
        )

        total = 0
        for X_batch, _ in stream_joined_embeddings(conn):
            ipca.partial_fit(X_batch)
            total += X_batch.shape[0]
            if total % (BATCH_SIZE * 20) == 0:
                print(f"Fitting PCA: {total} rows processed")

        print("PCA fit complete")
        print("Explained variance ratio:", ipca.explained_variance_ratio_)

        # -------------------------
        # PASS 2: TRANSFORM + SAMPLE + MEANS
        # -------------------------
        sampler = StratifiedReservoir(MAX_PER_CATEGORY)
        mean_acc = MeanAccumulator()

        total = 0
        for X_batch, cats in stream_joined_embeddings(conn):
            Z = ipca.transform(X_batch)  # (B, 2)
            sampler.add_batch(Z, cats)
            mean_acc.add_batch(Z, cats)

            total += X_batch.shape[0]
            if total % (BATCH_SIZE * 20) == 0:
                print(f"Transforming: {total} rows processed")

        Z_plot, cats_plot = sampler.to_arrays()
        mean_cats, mean_pts, mean_counts = mean_acc.means()

        print(
            f"Plotting {Z_plot.shape[0]} sampled points "
            f"across {len(np.unique(cats_plot))} categories"
        )
        print(f"Computed means for {len(mean_cats)} categories (using all rows, not just sample).")

    finally:
        conn.close()

    # -------------------------
    # DISTANCES BETWEEN CLUSTER MEANS
    # -------------------------
    if len(mean_cats) >= 2:
        D = pairwise_distances(mean_pts)
        n = len(mean_cats)

        # Extract upper triangle pairs
        pairs = []
        for i in range(n):
            for j in range(i + 1, n):
                pairs.append((D[i, j], mean_cats[i], mean_cats[j]))

        pairs.sort(key=lambda x: x[0])  # closest first

        print("\nClosest category-mean pairs (Euclidean distance in PCA-space):")
        for dist, c1, c2 in pairs[:TOPK_DISTANCES]:
            print(f"  {c1:10s}  <->  {c2:10s}   dist={dist:.4f}")

    # -------------------------
    # PLOT: points low alpha, means full opacity on top
    # -------------------------
    if Z_plot.shape[0] == 0:
        print("No data to plot.")
        return

    unique, counts = np.unique(cats_plot, return_counts=True)
    order = np.argsort(-counts)

    plt.figure(figsize=(10, 7), dpi=400)

    # individual points
    for cat in unique[order]:
        mask = cats_plot == cat
        plt.scatter(
            Z_plot[mask, 0],
            Z_plot[mask, 1],
            s=POINT_SIZE,
            alpha=POINT_ALPHA,
            label="_nolegend_",
        )

    # cluster means (plot on top)
    plt.scatter(
        mean_pts[:, 0],
        mean_pts[:, 1],
        s=140,              # ⬅️ larger marker
        alpha=1.0,
        marker="X",
        edgecolor="black",  # helps visibility
        linewidths=0.6,
        zorder=10,
        label="Category mean",
    )

    texts = []
    for cat, (x, y), cnt in zip(mean_cats, mean_pts, mean_counts):
        texts.append(
            plt.text(
                x,
                y,
                cat,
                fontsize=9,      # ⬅️ larger text
                weight="bold",
                zorder=11,
            )
        )

    # Automatically adjust label positions to avoid overlap
    adjust_text(
        texts,
        arrowprops=dict(arrowstyle="-", lw=0.5, color="gray"),
        expand_points=(1.2, 1.4),
        expand_text=(1.2, 1.4),
    )

    """
    if ANNOTATE_MEANS:
        for cat, (x, y), cnt in zip(mean_cats, mean_pts, mean_counts):
            plt.text(x, y, f" {cat}", fontsize=7)
    """

    plt.xlabel("PC1")
    plt.ylabel("PC2")
    plt.title("PCA of theorem embeddings (math categories) + cluster means")
    plt.legend(loc="best")
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()

# %%
# Figure 2
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
MAX_PER_CATEGORY = 25000
RANDOM_SEED = 42

# If paper.categories is not text[], change ::text[] to ::varchar[] (or remove cast).
SQL = """
SELECT
  p.primary_category,
  teq.embedding,
  (p.categories @> ARRAY['math.AG','math.NT']::text[]) AS is_both_ag_nt
FROM paper AS p
JOIN theorem AS t
  ON t.paper_id = p.paper_id
JOIN theorem_slogan AS ts
  ON ts.theorem_id = t.theorem_id
JOIN theorem_embedding_qwen AS teq
  ON teq.slogan_id = ts.slogan_id
WHERE teq.embedding IS NOT NULL
  AND p.primary_category IN ('math.AG', 'math.NT');
"""


# ============================================================
# STREAMING GENERATOR
# ============================================================
def stream_joined_embeddings(conn, batch_size=BATCH_SIZE):
    """
    Yields:
      X_batch: (B, d) float32 numpy array
      cats:    (B,) object numpy array (primary_category)
      both:    (B,) bool numpy array (paper is cross-listed AG+NT)
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
#     - "NT only"
#     - "AG & NT (cross-listed)"
# ============================================================
class GroupCapSampler:
    def __init__(self, max_per_group=None, seed=RANDOM_SEED):
        self.max_per_group = max_per_group
        self.rng = np.random.default_rng(seed)
        self.seen = {"AG only": 0, "NT only": 0, "AG & NT": 0}
        self.keep = {"AG only": [], "NT only": [], "AG & NT": []}

    def _group(self, primary_cat: str, both: bool) -> str:
        if both:
            return "AG & NT"
        if primary_cat == "math.AG":
            return "AG only"
        return "NT only"

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
    if groups["NT only"].shape[0] > 0:
        plt.scatter(groups["NT only"][:, 0], groups["NT only"][:, 1], s=6, alpha=0.35, label="NT only")
    if groups["AG & NT"].shape[0] > 0:
        plt.scatter(groups["AG & NT"][:, 0], groups["AG & NT"][:, 1], s=8, alpha=1, label="AG & NT (cross-listed)")

    plt.xlabel("PC1")
    plt.ylabel("PC2")
    plt.title("PCA of theorem embeddings: math.AG vs math.NT, cross-listed highlighted")
    plt.legend(markerscale=2)
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()