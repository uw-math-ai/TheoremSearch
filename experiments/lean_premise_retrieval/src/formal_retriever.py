"""Local dense retriever over the formal slogan-embedding index.

Replaces the TheoremSearch REST API + body-matching IDMapper for the formal
premise-retrieval objective. The corpus is v2's formal slogans, embedded 1:1
(qwen3-235b slogan -> 4096-d vector). Because the index is keyed by v2
statement_id, retrieval results ARE graph node ids — no cross-DB bridging.

Two query entry points:
  - search_by_vec(qvec, k, exclude_ids): cosine top-k. The primitive.
  - search(query_text, k): embeds the text first (needs an embedder); used by
    RL rollouts where the agent emits text queries.

For the similarity baseline (query = a target's own slogan), use the target's
row vector directly via vec_for(statement_id) — no embedder needed.
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np


class FormalRetriever:
    def __init__(self, emb_path: str | Path, ids_path: str | Path,
                 slogans_path: str | Path | None = None,
                 normalize: bool = True):
        self.ids: list[str] = json.loads(Path(ids_path).read_text())
        self.row_of: dict[str, int] = {sid: i for i, sid in enumerate(self.ids)}
        # Load to a RESIDENT float32 matrix once (BLAS-friendly), normalized so
        # cosine == dot. Built chunk-wise from the mmap'd f16 to cap peak memory
        # at ~one float32 copy (the f16 source stays on disk via mmap).
        src = np.load(emb_path, mmap_mode="r")  # [N, D] float16 on disk
        assert src.shape[0] == len(self.ids), "emb/ids length mismatch"
        self.emb = np.empty(src.shape, dtype=np.float32)
        for s in range(0, src.shape[0], 50000):
            e = s + 50000
            blk = src[s:e].astype(np.float32)
            if normalize:
                norms = np.linalg.norm(blk, axis=1, keepdims=True)
                norms[norms == 0] = 1.0
                blk = blk / norms
            self.emb[s:e] = blk
        del src

        self.slogans: dict[str, str] = {}
        if slogans_path and Path(slogans_path).exists():
            self.slogans = pickle.load(open(slogans_path, "rb"))

    def vec_for(self, statement_id: str) -> np.ndarray | None:
        i = self.row_of.get(statement_id)
        return None if i is None else self.emb[i].copy()

    def search_by_vec(self, qvec: np.ndarray, k: int,
                      exclude_ids: frozenset[str] | set[str] | None = None,
                      ) -> list[tuple[str, float]]:
        """Cosine top-k. qvec is normalized internally. Excluded ids are
        dropped before top-k so they never occupy a slot."""
        q = qvec.astype(np.float32)
        n = np.linalg.norm(q)
        if n:
            q = q / n
        scores = self.emb @ q  # [N], emb is resident normalized float32
        if exclude_ids:
            ex_rows = [self.row_of[s] for s in exclude_ids if s in self.row_of]
            if ex_rows:
                scores[np.fromiter(ex_rows, dtype=np.int64)] = -np.inf
        kk = min(k, scores.shape[0])
        top = np.argpartition(-scores, kk - 1)[:kk]
        top = top[np.argsort(-scores[top])]
        return [(self.ids[i], float(scores[i])) for i in top]

    def search(self, query_text: str, k: int, embedder, exclude_ids=None):
        """Text-query path for RL rollouts. `embedder(str)->np.ndarray[D]`."""
        return self.search_by_vec(embedder(query_text), k, exclude_ids)
