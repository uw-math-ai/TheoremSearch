"""Compare graph-walk depth with slogan-embedding cosine similarity.

The experiment runs four sampling schemes over the formal and informal
directed dependency graphs:

  parent-only
      Start at a statement and repeatedly sample one dependency uniformly.
      At depth d, compare the original seed with the depth-d endpoint.

  child-only
      Start at a statement and repeatedly sample one dependent uniformly.
      At depth d, compare the original seed with the depth-d endpoint.

  dual-parent
      Sample two distinct dependencies of a seed, then independently continue
      each branch toward dependencies. Compare the two branch endpoints.

  dual-child
      Sample two distinct dependents of a seed, then independently continue
      each branch toward dependents. Compare the two branch endpoints.

Every (formality, scheme, depth) bucket independently draws random embedded
seeds and attempts one fresh walk per seed. Successful walks are retained and
failed walks are replaced with newly drawn seeds until the requested sample
size is reached. Walks are constructed cheaply, then their final endpoint is
accepted only if its directed shortest-path distance from the seed is exactly
d. That final condition also certifies every prefix of the sampled path.

Dual walks have one additional exact condition. The seed supplies a shared
origin at radius d for the two endpoints. We reject the pair if some other
shared origin can reach both endpoints in fewer than d hops. For dual-parent,
that origin is a shared child/descendant; for dual-child, it is a shared
parent/ancestor. This prevents two branches from silently converging and being
reported at a depth larger than their true shared-origin depth.

Vectors are canonical qwen3-8b slogan embeddings generated from qwen3-235b
slogans. They are L2-normalized before cosine is computed as a dot product.
The raw-pair CSV is accompanied by a summary CSV containing pointwise
standard-error confidence intervals for every graph/scheme/depth mean.

Examples:
    python experiments/cos-distance/cos_depth_comparsion.py
    python experiments/cos-distance/cos_depth_comparsion.py --formality formal --scheme dual-parent
    python experiments/cos-distance/cos_depth_comparsion.py --formality informal --n-observations 100
"""

import argparse
import csv
import os
import random
import sys
import uuid
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from statistics import NormalDist
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
import psycopg2
from dotenv import load_dotenv

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

load_dotenv(os.path.join(_REPO_ROOT, ".env"))
from api.db import rds_conn  # noqa: E402


_EMBED_MODEL = "qwen3-8b"
_SLOGAN_MODELS = ["qwen3-235b"]
_STATEMENT_TIMEOUT_MS = 120_000
_EXACT_QUERY_BATCH = 2_000

_SCHEMES = ("parent-only", "child-only", "dual-parent", "dual-child")


@dataclass(frozen=True)
class GraphSample:
    formality: str
    scheme: str
    seed_id: str
    left_id: str
    right_id: str
    depth: int


@dataclass
class WalkResult:
    left_id: str
    right_id: str


@dataclass
class WalkAttempt:
    result: Optional[WalkResult]
    rejected_shorter: int = 0
    rejected_convergence: int = 0


@dataclass(frozen=True)
class BucketSummary:
    formality: str
    scheme: str
    depth: int
    n_target: int
    n_attempted: int
    n_successful: int
    n_failed: int
    n_unique_successful_seeds: int
    success_rate: float
    mean: float
    median: float
    variance: float
    std: float
    standard_error: float
    confidence_level: float
    ci_lower: float
    ci_upper: float


@contextmanager
def _cursor():
    """Open a short transaction with a longer timeout for graph queries."""
    with rds_conn("v2") as conn, conn.cursor() as cur:
        cur.execute(f"SET LOCAL statement_timeout = '{_STATEMENT_TIMEOUT_MS}';")
        yield cur


def _dep_table(formality: str) -> Tuple[str, str]:
    """Return (dependency table, filter excluding unresolved target edges)."""
    if formality == "formal":
        return "formal_dependency", ""
    return "informal_dependency", "AND dep_id IS NOT NULL"


def _scheme_direction(scheme: str) -> str:
    """Translate parent/child language to dependency-table edge direction."""
    return "src" if scheme in ("parent-only", "dual-parent") else "dep"


def _is_dual(scheme: str) -> bool:
    return scheme.startswith("dual-")


# ---------------------------------------------------------------------------
# Seed and embedding selection
# ---------------------------------------------------------------------------

def sample_seed_batch(
    formality: str,
    batch_size: int,
    excluded: Set[str],
) -> List[str]:
    """Draw fresh unique embedded seeds not present in ``excluded``.

    Random UUID successor lookups avoid ``ORDER BY random()`` over the full
    statement table. UUID primary keys are distributed across their keyspace,
    making this a fast approximately uniform row sampler. Rejection sampling
    conditions only on having a canonical embedding. UUID probes come from the
    script RNG, so ``--seed`` controls seed selection when the database is
    unchanged.
    """
    seeds: List[str] = []
    seen: Set[str] = set(excluded)
    for _ in range(50):
        remaining = batch_size - len(seeds)
        if remaining <= 0:
            break
        probes = [
            str(uuid.UUID(int=random.getrandbits(128), version=4))
            for _ in range(remaining * 5)
        ]
        with _cursor() as cur:
            cur.execute(
                """
                SELECT s.statement_id::text
                FROM unnest(%s::uuid[]) WITH ORDINALITY AS g(u, ord)
                CROSS JOIN LATERAL (
                    SELECT statement_id
                    FROM statement
                    WHERE formality = %s AND statement_id >= g.u
                    ORDER BY statement_id
                    LIMIT 1
                ) s
                ORDER BY g.ord
                """,
                (probes, formality),
            )
            candidates: List[str] = []
            for row in cur.fetchall():
                candidate = row[0]
                if candidate not in seen:
                    seen.add(candidate)
                    candidates.append(candidate)
            embedded = _statements_with_embedding(cur, candidates)

        for candidate in candidates:
            if candidate in embedded:
                seeds.append(candidate)
                if len(seeds) >= batch_size:
                    break
    return seeds[:batch_size]


def _statements_with_embedding(cur, ids: List[str]) -> Set[str]:
    """Return the subset having a canonical slogan embedding."""
    if not ids:
        return set()
    out: Set[str] = set()
    unique_ids = list(set(ids))
    for i in range(0, len(unique_ids), _EXACT_QUERY_BATCH):
        chunk = unique_ids[i : i + _EXACT_QUERY_BATCH]
        cur.execute(
            """
            SELECT DISTINCT st.statement_id::text
            FROM statement st
            JOIN slogan sl   ON sl.statement_id = st.statement_id
            JOIN embedding e ON e.slogan_id     = sl.slogan_id
            WHERE st.statement_id = ANY(%s::uuid[])
              AND e.model_name = %s
              AND sl.model_name = ANY(%s)
              AND NOT sl.insufficient_context
            """,
            (chunk, _EMBED_MODEL, _SLOGAN_MODELS),
        )
        out.update(r[0] for r in cur.fetchall())
    return out


# ---------------------------------------------------------------------------
# Exact graph traversal and verification
# ---------------------------------------------------------------------------

def _neighbors_batch(
    cur,
    table: str,
    edge_filter: str,
    direction: str,
    frontier: List[str],
) -> Set[str]:
    """Return all distinct one-hop neighbors of a frontier."""
    if not frontier:
        return set()
    if direction == "src":
        sql = (
            f"SELECT dep_id::text FROM {table} "
            f"WHERE src_id = ANY(%s::uuid[]) {edge_filter}"
        )
    else:
        sql = (
            f"SELECT src_id::text FROM {table} "
            "WHERE dep_id = ANY(%s::uuid[])"
        )
    cur.execute(sql, (frontier,))
    return {r[0] for r in cur.fetchall() if r[0] is not None}


def _neighbors_exact(
    cur,
    table: str,
    edge_filter: str,
    direction: str,
    frontier: Set[str],
) -> Set[str]:
    """Expand every frontier node, chunking SQL arrays without pruning."""
    nodes = list(frontier)
    out: Set[str] = set()
    for i in range(0, len(nodes), _EXACT_QUERY_BATCH):
        out.update(
            _neighbors_batch(
                cur,
                table,
                edge_filter,
                direction,
                nodes[i : i + _EXACT_QUERY_BATCH],
            )
        )
    return out


def _node_neighbors(
    cur, formality: str, direction: str, node_id: str,
) -> Set[str]:
    table, edge_filter = _dep_table(formality)
    neighbors = _neighbors_batch(
        cur, table, edge_filter, direction, [node_id])
    neighbors.discard(node_id)
    return neighbors


def _reachable_exact(
    cur,
    table: str,
    edge_filter: str,
    direction: str,
    start: str,
    max_depth: int,
) -> Set[str]:
    """Return every node reachable in at most ``max_depth`` directed hops."""
    visited: Set[str] = {start}
    frontier: Set[str] = {start}
    for _ in range(max_depth):
        neighbors = _neighbors_exact(
            cur, table, edge_filter, direction, frontier)
        frontier = neighbors - visited
        if not frontier:
            break
        visited.update(frontier)
    return visited


def _reverse_reaches_forward(
    cur,
    table: str,
    edge_filter: str,
    reverse_direction: str,
    target: str,
    max_depth: int,
    forward_reachable: Set[str],
) -> bool:
    """Whether reverse search from target meets a forward-reachable set."""
    visited: Set[str] = {target}
    frontier: Set[str] = {target}
    if target in forward_reachable:
        return True
    for _ in range(max_depth):
        neighbors = _neighbors_exact(
            cur, table, edge_filter, reverse_direction, frontier)
        frontier = neighbors - visited
        if not frontier:
            return False
        if not forward_reachable.isdisjoint(frontier):
            return True
        visited.update(frontier)
    return False


def _distance_verifier_state(
    cur,
    formality: str,
    direction: str,
    seed: str,
    candidate_depth: int,
) -> Tuple[str, str, str, int, Set[str]]:
    """Build shared meet-in-the-middle state for depth-d candidates."""
    table, edge_filter = _dep_table(formality)
    shorter_bound = candidate_depth - 1
    forward_depth = (shorter_bound + 1) // 2
    reverse_depth = shorter_bound - forward_depth
    reverse_direction = "dep" if direction == "src" else "src"
    forward_reachable = _reachable_exact(
        cur, table, edge_filter, direction, seed, forward_depth)
    return (
        table,
        edge_filter,
        reverse_direction,
        reverse_depth,
        forward_reachable,
    )


def _has_shorter_seed_path(
    cur,
    target: str,
    verifier_state: Tuple[str, str, str, int, Set[str]],
) -> bool:
    table, edge_filter, reverse_direction, reverse_depth, forward = (
        verifier_state
    )
    return _reverse_reaches_forward(
        cur,
        table,
        edge_filter,
        reverse_direction,
        target,
        reverse_depth,
        forward,
    )


def _choose_random_neighbor(
    cur,
    candidates: Set[str],
    excluded: Set[str],
    require_embedding: bool,
) -> Optional[str]:
    """Choose one eligible neighbor uniformly without graph verification."""
    candidates = candidates - excluded
    if require_embedding:
        candidates = candidates & _statements_with_embedding(
            cur, list(candidates))
    if not candidates:
        return None
    return random.choice(sorted(candidates))


def _choose_random_neighbor_pair(
    cur,
    left_candidates: Set[str],
    right_candidates: Set[str],
    excluded: Set[str],
    require_embedding: bool,
) -> Optional[Tuple[str, str]]:
    """Choose uniformly from distinct ordered pairs of eligible neighbors."""
    left_candidates = left_candidates - excluded
    right_candidates = right_candidates - excluded
    if require_embedding:
        embedded = _statements_with_embedding(
            cur, list(left_candidates | right_candidates))
        left_candidates &= embedded
        right_candidates &= embedded

    left = sorted(left_candidates)
    right = sorted(right_candidates)
    if not left or not right:
        return None

    right_set = set(right)
    pair_count = sum(len(right) - (left_id in right_set) for left_id in left)
    if pair_count == 0:
        return None
    pair_index = random.randrange(pair_count)
    for left_id in left:
        available_right = len(right) - (left_id in right_set)
        if pair_index < available_right:
            right_options = [node for node in right if node != left_id]
            return left_id, right_options[pair_index]
        pair_index -= available_right
    return None


def _has_closer_common_origin(
    cur,
    formality: str,
    direction: str,
    left_id: str,
    right_id: str,
    candidate_depth: int,
) -> bool:
    """Whether both endpoints have a shared origin at radius < depth."""
    if left_id == right_id:
        return True
    table, edge_filter = _dep_table(formality)
    reverse_direction = "dep" if direction == "src" else "src"
    closer_radius = candidate_depth - 1
    left_origins = _reachable_exact(
        cur,
        table,
        edge_filter,
        reverse_direction,
        left_id,
        closer_radius,
    )
    right_origins = _reachable_exact(
        cur,
        table,
        edge_filter,
        reverse_direction,
        right_id,
        closer_radius,
    )
    return not left_origins.isdisjoint(right_origins)


# ---------------------------------------------------------------------------
# Walk sampling
# ---------------------------------------------------------------------------

def _sample_single_walk(
    cur,
    formality: str,
    direction: str,
    seed: str,
    target_depth: int,
) -> WalkAttempt:
    current = seed
    visited: Set[str] = {seed}
    for depth in range(1, target_depth + 1):
        candidates = _node_neighbors(cur, formality, direction, current)
        current = _choose_random_neighbor(
            cur,
            candidates,
            visited,
            require_embedding=(depth == target_depth),
        )
        if current is None:
            return WalkAttempt(None)
        visited.add(current)

    verifier = _distance_verifier_state(
        cur, formality, direction, seed, target_depth)
    if _has_shorter_seed_path(cur, current, verifier):
        return WalkAttempt(None, rejected_shorter=1)
    return WalkAttempt(WalkResult(seed, current))


def _sample_dual_walk(
    cur,
    formality: str,
    direction: str,
    seed: str,
    target_depth: int,
) -> WalkAttempt:
    initial = _node_neighbors(cur, formality, direction, seed)
    chosen = _choose_random_neighbor_pair(
        cur,
        initial,
        initial,
        {seed},
        require_embedding=(target_depth == 1),
    )
    if chosen is None:
        return WalkAttempt(None)
    left, right = chosen
    visited: Set[str] = {seed, left, right}

    for depth in range(2, target_depth + 1):
        left_candidates = _node_neighbors(cur, formality, direction, left)
        right_candidates = _node_neighbors(cur, formality, direction, right)
        chosen = _choose_random_neighbor_pair(
            cur,
            left_candidates,
            right_candidates,
            visited,
            require_embedding=(depth == target_depth),
        )
        if chosen is None:
            return WalkAttempt(None)
        left, right = chosen
        visited.update((left, right))

    verifier = _distance_verifier_state(
        cur, formality, direction, seed, target_depth)
    rejected_shorter = int(
        _has_shorter_seed_path(cur, left, verifier))
    rejected_shorter += int(
        _has_shorter_seed_path(cur, right, verifier))
    if rejected_shorter:
        return WalkAttempt(None, rejected_shorter=rejected_shorter)

    if _has_closer_common_origin(
        cur, formality, direction, left, right, target_depth
    ):
        return WalkAttempt(None, rejected_convergence=1)
    return WalkAttempt(WalkResult(left, right))


def _sample_walk_resilient(
    formality: str,
    scheme: str,
    seed: str,
    target_depth: int,
) -> WalkAttempt:
    direction = _scheme_direction(scheme)
    for attempt in range(2):
        try:
            with _cursor() as cur:
                if _is_dual(scheme):
                    return _sample_dual_walk(
                        cur, formality, direction, seed, target_depth)
                return _sample_single_walk(
                    cur, formality, direction, seed, target_depth)
        except psycopg2.OperationalError:
            if attempt == 1:
                return WalkAttempt(None)
        except psycopg2.errors.QueryCanceled:
            return WalkAttempt(None)
    return WalkAttempt(None)


def collect_scheme_samples(
    formality: str,
    scheme: str,
    depths: List[int],
    n_observations: int,
    seed_batch: int,
) -> Tuple[List[GraphSample], Dict[int, int]]:
    """Independently rejection-sample each depth to ``n_observations``."""
    samples: List[GraphSample] = []
    attempted_by_depth: Dict[int, int] = {}

    for depth in depths:
        successful = 0
        attempted_seeds: Set[str] = set()
        rejected_shorter = 0
        rejected_convergence = 0
        empty_seed_batches = 0

        while successful < n_observations:
            seeds = sample_seed_batch(
                formality, seed_batch, attempted_seeds)
            if not seeds:
                empty_seed_batches += 1
                if empty_seed_batches >= 5:
                    print(
                        f"  {formality}/{scheme} depth {depth}: unable to "
                        "draw additional unique embedded seeds; stopping",
                        file=sys.stderr,
                    )
                    break
                continue
            empty_seed_batches = 0

            for seed in seeds:
                attempted_seeds.add(seed)
                attempt = _sample_walk_resilient(
                    formality, scheme, seed, depth)
                rejected_shorter += attempt.rejected_shorter
                rejected_convergence += attempt.rejected_convergence
                if attempt.result is None:
                    continue
                result = attempt.result

                samples.append(
                    GraphSample(
                        formality,
                        scheme,
                        seed,
                        result.left_id,
                        result.right_id,
                        depth,
                    )
                )
                successful += 1
                if successful >= n_observations:
                    break

        attempted = len(attempted_seeds)
        attempted_by_depth[depth] = attempted
        failures = attempted - successful

        convergence = (
            f", convergence rejects={rejected_convergence}"
            if _is_dual(scheme)
            else ""
        )
        print(
            f"  {formality}/{scheme} depth {depth}: {successful}/"
            f"{n_observations} successful from {attempted} attempts, "
            f"failed={failures}, shorter-path rejects={rejected_shorter}"
            f"{convergence}",
            file=sys.stderr,
        )

    return samples, attempted_by_depth


# ---------------------------------------------------------------------------
# Embeddings, output, and reporting
# ---------------------------------------------------------------------------

def fetch_embeddings(ids: List[str]) -> Dict[str, np.ndarray]:
    """Fetch and L2-normalize the earliest canonical vector per statement."""
    out: Dict[str, np.ndarray] = {}
    unique_ids = list(set(ids))
    for i in range(0, len(unique_ids), 1_000):
        chunk = unique_ids[i : i + 1_000]
        with _cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (st.statement_id)
                       st.statement_id::text, e.embedding
                FROM statement st
                JOIN slogan sl   ON sl.statement_id = st.statement_id
                JOIN embedding e ON e.slogan_id     = sl.slogan_id
                WHERE st.statement_id = ANY(%s::uuid[])
                  AND e.model_name = %s
                  AND sl.model_name = ANY(%s)
                  AND NOT sl.insufficient_context
                ORDER BY st.statement_id, sl.created_at
                """,
                (chunk, _EMBED_MODEL, _SLOGAN_MODELS),
            )
            rows = cur.fetchall()
        for statement_id, embedding in rows:
            vector = _parse_vec(embedding)
            norm = np.linalg.norm(vector)
            out[statement_id] = vector / norm if norm > 0 else vector
    return out


def _parse_vec(embedding) -> np.ndarray:
    if isinstance(embedding, str):
        return np.fromstring(
            embedding.strip()[1:-1], sep=",", dtype=np.float32)
    return np.asarray(embedding, dtype=np.float32)


def _random_baselines(
    formality: str,
    pool: List[str],
    n_pairs: int,
) -> List[GraphSample]:
    if len(pool) < 2:
        return []
    return [
        GraphSample(formality, "random", a, a, b, -1)
        for a, b in (random.sample(pool, 2) for _ in range(n_pairs))
    ]


def _write_csv(
    path: str,
    rows: List[Tuple[GraphSample, float]],
) -> None:
    with open(path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(
            [
                "formality",
                "scheme",
                "seed_id",
                "left_id",
                "right_id",
                "depth",
                "cosine",
            ]
        )
        for sample, cosine in rows:
            writer.writerow(
                [
                    sample.formality,
                    sample.scheme,
                    sample.seed_id,
                    sample.left_id,
                    sample.right_id,
                    "inf" if sample.depth == -1 else sample.depth,
                    f"{cosine:.6f}",
                ]
            )


def _summarize_rows(
    rows: List[Tuple[GraphSample, float]],
    confidence_level: float,
    attempt_stats: Dict[Tuple[str, str, int], Tuple[int, int]],
) -> List[BucketSummary]:
    grouped: Dict[
        Tuple[str, str, int], List[Tuple[str, float]]
    ] = defaultdict(list)
    for sample, cosine in rows:
        grouped[(sample.formality, sample.scheme, sample.depth)].append(
            (sample.seed_id, cosine))

    critical_value = NormalDist().inv_cdf(
        0.5 + confidence_level / 2.0)
    summaries: List[BucketSummary] = []
    bucket_keys = sorted(set(grouped) | set(attempt_stats))
    for formality, scheme, depth in bucket_keys:
        observations = grouped.get((formality, scheme, depth), [])
        values = np.asarray([cosine for _, cosine in observations], dtype=float)
        n_successful = len(values)
        n_target, n_attempted = attempt_stats.get(
            (formality, scheme, depth), (n_successful, n_successful))
        n_failed = max(0, n_attempted - n_successful)
        n_unique_successful_seeds = len(
            {seed_id for seed_id, _ in observations})
        success_rate = (
            n_successful / n_attempted
            if n_attempted > 0 else float("nan"))
        variance = (
            float(values.var(ddof=1))
            if n_successful >= 2 else float("nan"))
        std = (
            float(values.std(ddof=1))
            if n_successful >= 2 else float("nan"))
        mean = float(values.mean()) if n_successful else float("nan")
        median = float(np.median(values)) if n_successful else float("nan")
        if n_successful >= 2:
            standard_error = std / np.sqrt(n_successful)
            margin = critical_value * standard_error
            ci_lower = mean - margin
            ci_upper = mean + margin
        else:
            standard_error = float("nan")
            ci_lower = float("nan")
            ci_upper = float("nan")
        summaries.append(
            BucketSummary(
                formality=formality,
                scheme=scheme,
                depth=depth,
                n_target=n_target,
                n_attempted=n_attempted,
                n_successful=n_successful,
                n_failed=n_failed,
                n_unique_successful_seeds=n_unique_successful_seeds,
                success_rate=success_rate,
                mean=mean,
                median=median,
                variance=variance,
                std=std,
                standard_error=standard_error,
                confidence_level=confidence_level,
                ci_lower=ci_lower,
                ci_upper=ci_upper,
            )
        )
    return summaries


def _write_summary_csv(path: str, summaries: List[BucketSummary]) -> None:
    def formatted(value: float) -> str:
        return "" if np.isnan(value) else f"{value:.8f}"

    with open(path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(
            [
                "formality",
                "scheme",
                "depth",
                "n_target",
                "n_attempted",
                "n_successful",
                "n_failed",
                "n_unique_successful_seeds",
                "success_rate",
                "mean_cosine",
                "median_cosine",
                "variance",
                "std",
                "standard_error",
                "confidence_level",
                "ci_lower",
                "ci_upper",
            ]
        )
        for summary in summaries:
            writer.writerow(
                [
                    summary.formality,
                    summary.scheme,
                    "inf" if summary.depth == -1 else summary.depth,
                    summary.n_target,
                    summary.n_attempted,
                    summary.n_successful,
                    summary.n_failed,
                    summary.n_unique_successful_seeds,
                    formatted(summary.success_rate),
                    formatted(summary.mean),
                    formatted(summary.median),
                    formatted(summary.variance),
                    formatted(summary.std),
                    formatted(summary.standard_error),
                    f"{summary.confidence_level:.4f}",
                    formatted(summary.ci_lower),
                    formatted(summary.ci_upper),
                ]
            )


def _report(
    rows: List[Tuple[GraphSample, float]],
    summaries: List[BucketSummary],
) -> None:
    formalities = sorted({summary.formality for summary in summaries})
    for formality in formalities:
        print(f"\n=== {formality} graph ===")
        schemes = [
            scheme
            for scheme in (*_SCHEMES, "random")
            if any(
                summary.formality == formality and summary.scheme == scheme
                for summary in summaries
            )
        ]
        for scheme in schemes:
            print(f"\n{scheme}")
            print(
                f"{'depth':>8} {'target':>8} {'attempt':>8} "
                f"{'success':>8} {'rate':>8} "
                f"{'mean':>9} "
                f"{'CI low':>9} {'CI high':>9} {'SE':>9}"
            )
            scheme_summaries = sorted(
                (
                    summary
                    for summary in summaries
                    if summary.formality == formality
                    and summary.scheme == scheme
                ),
                key=lambda summary: (
                    summary.depth == -1,
                    summary.depth,
                ),
            )
            for summary in scheme_summaries:
                label = "random" if summary.depth == -1 else str(summary.depth)
                ci_lower = (
                    "n/a" if np.isnan(summary.ci_lower)
                    else f"{summary.ci_lower:.4f}"
                )
                ci_upper = (
                    "n/a" if np.isnan(summary.ci_upper)
                    else f"{summary.ci_upper:.4f}"
                )
                standard_error = (
                    "n/a" if np.isnan(summary.standard_error)
                    else f"{summary.standard_error:.4f}"
                )
                print(
                    f"{label:>8} {summary.n_target:>8} "
                    f"{summary.n_attempted:>8} {summary.n_successful:>8} "
                    f"{summary.success_rate:>8.3f} "
                    f"{summary.mean:>9.4f} "
                    f"{ci_lower:>9} {ci_upper:>9} {standard_error:>9}"
                )

            connected = [
                (sample.depth, cosine)
                for sample, cosine in rows
                if sample.formality == formality
                and sample.scheme == scheme
                and sample.depth >= 1
            ]
            if len(connected) >= 2:
                distances = np.asarray([x[0] for x in connected], dtype=float)
                cosines = np.asarray([x[1] for x in connected], dtype=float)
                if distances.std() > 0:
                    pearson = float(np.corrcoef(distances, cosines)[0, 1])
                    spearman = _spearman(distances, cosines)
                    print(
                        f"  Pearson={pearson:+.4f}; "
                        f"Spearman={spearman:+.4f}"
                    )


def _rank_with_ties(values: np.ndarray) -> np.ndarray:
    """Return average ranks, assigning equal values equal ranks."""
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = (start + end - 1) / 2.0
        start = end
    return ranks


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    return float(np.corrcoef(_rank_with_ties(x), _rank_with_ties(y))[0, 1])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--formality",
        choices=["informal", "formal", "both"],
        default="both",
        help="Graph type to sample (default: both).",
    )
    parser.add_argument(
        "--scheme",
        choices=[*_SCHEMES, "all"],
        default="all",
        help="Sampling scheme to run (default: all four).",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=6,
        help="Independently sample each depth from 1 through this value.",
    )
    parser.add_argument(
        "--n-observations",
        "--n-seeds",
        "--n-per-depth",
        dest="n_observations",
        type=int,
        default=1_000,
        help="Successful unique-seed observations per bucket (default: 1000).",
    )
    parser.add_argument(
        "--seed-batch",
        type=int,
        default=100,
        help="Fresh candidate starting statements drawn per database batch.",
    )
    parser.add_argument(
        "--n-random",
        type=int,
        default=5_000,
        help="Random cosine-baseline pairs per graph.",
    )
    parser.add_argument(
        "--confidence-level",
        type=float,
        default=0.95,
        help="Pointwise confidence level for mean cosine (default: 0.95).",
    )
    parser.add_argument("--seed", type=int, default=0, help="RNG seed.")
    parser.add_argument("--out", default=None, help="Raw-pair CSV path.")
    parser.add_argument(
        "--summary-out",
        default=None,
        help="Summary/error-bar CSV path (default: <out>_summary.csv).",
    )
    args = parser.parse_args()

    if args.max_depth < 1:
        parser.error("--max-depth must be at least 1")
    if args.n_observations < 1:
        parser.error("--n-observations must be at least 1")
    if args.seed_batch < 1:
        parser.error("--seed-batch must be at least 1")
    if args.n_random < 0:
        parser.error("--n-random cannot be negative")
    if not 0.0 < args.confidence_level < 1.0:
        parser.error("--confidence-level must be between 0 and 1")

    random.seed(args.seed)
    np.random.seed(args.seed)

    formalities = (
        ["informal", "formal"]
        if args.formality == "both"
        else [args.formality]
    )
    schemes = list(_SCHEMES) if args.scheme == "all" else [args.scheme]
    depths = list(range(1, args.max_depth + 1))
    output_path = args.out or (
        f"cos_depth_{args.formality}_{args.scheme}.csv"
    )
    output_root, output_extension = os.path.splitext(output_path)
    summary_path = args.summary_out or (
        f"{output_root}_summary{output_extension or '.csv'}"
    )

    samples: List[GraphSample] = []
    attempt_stats: Dict[Tuple[str, str, int], Tuple[int, int]] = {}
    for formality in formalities:
        for scheme in schemes:
            print(
                f"Sampling {formality}/{scheme} at depths {depths}...",
                file=sys.stderr,
            )
            scheme_samples, attempted_by_depth = collect_scheme_samples(
                formality,
                scheme,
                depths,
                args.n_observations,
                args.seed_batch,
            )
            samples.extend(scheme_samples)
            for depth, n_attempted in attempted_by_depth.items():
                attempt_stats[(formality, scheme, depth)] = (
                    args.n_observations, n_attempted)

    if not samples:
        print("No graph samples were collected.", file=sys.stderr)
        return

    needed = {
        node_id
        for sample in samples
        for node_id in (sample.left_id, sample.right_id)
    }
    print(f"Fetching {len(needed)} embeddings...", file=sys.stderr)
    embeddings = fetch_embeddings(list(needed))

    for formality in formalities:
        pool = sorted(
            {
                node_id
                for sample in samples
                if sample.formality == formality
                for node_id in (sample.left_id, sample.right_id)
                if node_id in embeddings
            }
        )
        baselines = _random_baselines(formality, pool, args.n_random)
        samples.extend(baselines)
        attempt_stats[(formality, "random", -1)] = (
            args.n_random, len(baselines))

    rows: List[Tuple[GraphSample, float]] = []
    for sample in samples:
        left_vector = embeddings.get(sample.left_id)
        right_vector = embeddings.get(sample.right_id)
        if left_vector is None or right_vector is None:
            continue
        rows.append(
            (sample, float(np.dot(left_vector, right_vector)))
        )

    if not rows:
        print("No sampled pairs had two usable embeddings.", file=sys.stderr)
        return

    _write_csv(output_path, rows)
    print(f"Wrote {len(rows)} rows to {output_path}", file=sys.stderr)
    summaries = _summarize_rows(
        rows,
        args.confidence_level,
        attempt_stats,
    )
    _write_summary_csv(summary_path, summaries)
    print(
        f"Wrote {len(summaries)} confidence-interval rows to {summary_path}",
        file=sys.stderr,
    )
    _report(rows, summaries)


if __name__ == "__main__":
    main()
