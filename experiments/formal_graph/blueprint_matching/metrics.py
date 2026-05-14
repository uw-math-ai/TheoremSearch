"""Similarity metrics for the blueprint↔formal slogan benchmark.

Every metric exposes the same shape::

    fn(texts_a: list[str], texts_b: list[str]) -> np.ndarray   # shape (N, M)

…where higher values mean "more similar". The matrix is dense and built in
memory; we're operating on ~30×30 slogan grids so this is fine.

Embedding and LLM-judge calls are cached on disk under ``cache/`` so that
re-running the benchmark is essentially free after the first pass.
"""
from __future__ import annotations

import hashlib
import json
import math
import pickle
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable

import numpy as np
from tqdm import tqdm

CACHE_DIR = Path(__file__).resolve().parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
# Slogans are clean ASCII English by construction (the pilot prompt forbids
# LaTeX / Unicode math), so normalization stays minimal: lowercase + collapse
# whitespace. No symbol substitution needed.

def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def tokens(s: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", normalize(s))


# ---------------------------------------------------------------------------
# String / token level
# ---------------------------------------------------------------------------

def edit_norm(texts_a: list[str], texts_b: list[str]) -> np.ndarray:
    from rapidfuzz.distance import Levenshtein
    n, m = len(texts_a), len(texts_b)
    out = np.zeros((n, m))
    a_norm = [normalize(a) for a in texts_a]
    b_norm = [normalize(b) for b in texts_b]
    for i, a in enumerate(a_norm):
        for j, b in enumerate(b_norm):
            out[i, j] = Levenshtein.normalized_similarity(a, b)
    return out


def jaccard_tokens(texts_a: list[str], texts_b: list[str]) -> np.ndarray:
    a_sets = [set(tokens(a)) for a in texts_a]
    b_sets = [set(tokens(b)) for b in texts_b]
    n, m = len(a_sets), len(b_sets)
    out = np.zeros((n, m))
    for i, ta in enumerate(a_sets):
        for j, tb in enumerate(b_sets):
            out[i, j] = len(ta & tb) / max(1, len(ta | tb))
    return out


def char_ngram_jaccard(texts_a: list[str], texts_b: list[str], ngram: int = 3) -> np.ndarray:
    def grams(s: str) -> set:
        s = normalize(s)
        return {s[i:i+ngram] for i in range(max(0, len(s) - ngram + 1))}
    a_g = [grams(s) for s in texts_a]
    b_g = [grams(s) for s in texts_b]
    n, m = len(a_g), len(b_g)
    out = np.zeros((n, m))
    for i, ga in enumerate(a_g):
        for j, gb in enumerate(b_g):
            out[i, j] = len(ga & gb) / max(1, len(ga | gb))
    return out


def difflib_ratio(texts_a: list[str], texts_b: list[str]) -> np.ndarray:
    a_n = [normalize(s) for s in texts_a]
    b_n = [normalize(s) for s in texts_b]
    n, m = len(a_n), len(b_n)
    out = np.zeros((n, m))
    for i, a in enumerate(a_n):
        for j, b in enumerate(b_n):
            out[i, j] = SequenceMatcher(None, a, b).ratio()
    return out


# ---------------------------------------------------------------------------
# IR-style
# ---------------------------------------------------------------------------

def tfidf_cosine(texts_a: list[str], texts_b: list[str]) -> np.ndarray:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    a_norm = [normalize(s) for s in texts_a]
    b_norm = [normalize(s) for s in texts_b]
    vec = TfidfVectorizer().fit(a_norm + b_norm)
    return np.asarray(cosine_similarity(vec.transform(a_norm), vec.transform(b_norm)))


def bm25(texts_a: list[str], texts_b: list[str], k1: float = 1.5, b: float = 0.75) -> np.ndarray:
    """``texts_b`` are documents, ``texts_a`` are queries. Output normalized
    to [0, 1] by dividing by the max observed score so it's comparable to the
    other metrics."""
    docs = [tokens(s) for s in texts_b]
    if not docs:
        return np.zeros((len(texts_a), 0))
    avgdl = sum(len(d) for d in docs) / len(docs)
    df = Counter()
    for d in docs:
        for t in set(d):
            df[t] += 1
    N = len(docs)
    idf = {t: math.log((N - n + 0.5) / (n + 0.5) + 1) for t, n in df.items()}

    out = np.zeros((len(texts_a), len(docs)))
    for j, d in enumerate(docs):
        tf = Counter(d)
        for i, q in enumerate(texts_a):
            score = 0.0
            for t in tokens(q):
                if t not in tf:
                    continue
                denom = tf[t] + k1 * (1 - b + b * len(d) / max(avgdl, 1))
                score += idf.get(t, 0.0) * (tf[t] * (k1 + 1)) / denom
            out[i, j] = score
    mx = out.max()
    return out / mx if mx > 0 else out


# ---------------------------------------------------------------------------
# Embeddings (cached on disk per model)
# ---------------------------------------------------------------------------

def _embed_with_cache(texts: list[str], cache_key: str, embed_fn: Callable) -> np.ndarray:
    cache_path = CACHE_DIR / f"emb_{cache_key.replace('/', '_')}.pkl"
    cache: dict[str, np.ndarray] = (
        pickle.loads(cache_path.read_bytes()) if cache_path.exists() else {}
    )
    miss = [t for t in texts if t not in cache]
    if miss:
        vecs = embed_fn(miss)
        for t, v in zip(miss, vecs):
            cache[t] = np.asarray(v, dtype=np.float32)
        cache_path.write_bytes(pickle.dumps(cache))
    return np.stack([cache[t] for t in texts])


def _cosine_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a_n = a / np.clip(np.linalg.norm(a, axis=1, keepdims=True), 1e-12, None)
    b_n = b / np.clip(np.linalg.norm(b, axis=1, keepdims=True), 1e-12, None)
    return a_n @ b_n.T


_NEBIUS_EMBED_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
_NEBIUS_CHAT_BASE_URL  = "https://api.studio.nebius.ai/v1/"


def nebius_embedding_cos(
    texts_a: list[str], texts_b: list[str], model: str = "Qwen/Qwen3-Embedding-8B",
) -> np.ndarray:
    """Nebius-hosted embeddings via the OpenAI-compatible endpoint. Requires
    ``NEBIUS_API_KEY`` in the environment."""
    import os
    from openai import OpenAI
    client = OpenAI(
        api_key=os.environ["NEBIUS_API_KEY"],
        base_url=_NEBIUS_EMBED_BASE_URL,
    )

    def embed(batch):
        r = client.embeddings.create(model=model, input=batch, encoding_format="float")
        return [d.embedding for d in r.data]

    cache_key = f"nebius_{model}"
    e_a = _embed_with_cache(texts_a, cache_key, embed)
    e_b = _embed_with_cache(texts_b, cache_key, embed)
    return _cosine_matrix(e_a, e_b)


# ---------------------------------------------------------------------------
# LLM judge (one call per pair, cached)
# ---------------------------------------------------------------------------

_JUDGE_BATCH_PROMPT = (
    "You are checking whether a 'reference' slogan describes the SAME mathematical "
    "statement as each candidate slogan in the list below.\n"
    "For every candidate, return a confidence rating:\n"
    "  high   - clearly the same statement\n"
    "  medium - probably the same; some uncertainty\n"
    "  low    - possibly related but doubtful\n"
    "  none   - unrelated\n"
    "Be strict.\n\n"
    "Return strict JSON only — no prose, no markdown. A JSON array with exactly "
    "{n} entries echoing each candidate's ``id`` verbatim:\n"
    "[{{\"id\": \"cand_0\", \"confidence\": \"high\"|\"medium\"|\"low\"|\"none\"}}, ...]\n\n"
    "Reference slogan:\n{reference}\n\n"
    "Candidates:\n{candidates}\n"
)

_CONFIDENCE_TO_SCORE = {"high": 1.0, "medium": 2/3, "low": 1/3, "none": 0.0}
_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def _judge_cache_path(model: str) -> Path:
    return CACHE_DIR / f"judge_{model.replace('/', '_')}.jsonl"


def _load_judge_cache(model: str) -> dict[str, float]:
    path = _judge_cache_path(model)
    cache: dict[str, float] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            cache[rec["key"]] = rec["score"]
    return cache


def _pair_cache_key(model: str, a: str, b: str) -> str:
    return hashlib.sha1(f"{model}\n||\n{a}\n||\n{b}".encode()).hexdigest()


def _run_judge_batch(client, model: str, reference: str, candidates: list[str]) -> list[str]:
    """One LLM call covering ``candidates`` for a single ``reference``.
    Returns a list of confidence labels (same length as ``candidates``).
    Missing/mangled positions come back as ``""`` and the caller treats them
    as score 0."""
    candidates_text = "\n".join(
        f"- id=cand_{idx}: {text}" for idx, text in enumerate(candidates)
    )
    prompt = _JUDGE_BATCH_PROMPT.format(
        n=len(candidates), reference=reference, candidates=candidates_text,
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        # Each entry is ~30 tokens of JSON; pad for safety.
        max_tokens=80 * len(candidates) + 200,
    )
    text = resp.choices[0].message.content or ""
    by_id: dict[str, str] = {}
    m = _JSON_ARRAY_RE.search(text)
    if m:
        try:
            arr = json.loads(m.group())
            if isinstance(arr, list):
                for entry in arr:
                    if isinstance(entry, dict):
                        cid = entry.get("id", "")
                        conf = str(entry.get("confidence", "")).strip().lower()
                        by_id[cid] = conf
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
    return [by_id.get(f"cand_{idx}", "") for idx in range(len(candidates))]


def llm_judge(
    texts_a: list[str], texts_b: list[str],
    model: str = "Qwen/Qwen3-235B-A22B-Instruct-2507",
    batch_size: int = 10,
    workers: int = 8,
) -> np.ndarray:
    """Discrete-confidence judge over Nebius (OpenAI-compatible). Pairs are
    batched: a single LLM call covers one informal reference vs up to
    ``batch_size`` candidates. Batches run concurrently across ``workers``
    threads. Each pair's score caches under ``cache/judge_<model>.jsonl`` so
    re-runs only call the API for new pairs.

    Each pair → {high, medium, low, none} → {1.0, 2/3, 1/3, 0.0}.
    Requires ``NEBIUS_API_KEY``.
    """
    import os
    from openai import OpenAI
    client = OpenAI(
        api_key=os.environ["NEBIUS_API_KEY"],
        base_url=_NEBIUS_CHAT_BASE_URL,
    )
    cache = _load_judge_cache(model)
    cache_path = _judge_cache_path(model)
    out = np.zeros((len(texts_a), len(texts_b)))

    # Fill cached pairs, collect the rest per-informal.
    pending: dict[int, list[tuple[int, str]]] = defaultdict(list)
    for i, a in enumerate(texts_a):
        for j, b in enumerate(texts_b):
            key = _pair_cache_key(model, a, b)
            if key in cache:
                out[i, j] = cache[key]
            else:
                pending[i].append((j, key))

    # Chunk pending pairs into batches keyed on the same informal i.
    batches: list[tuple[int, list[tuple[int, str]]]] = []
    for i, items in pending.items():
        for k in range(0, len(items), batch_size):
            batches.append((i, items[k:k + batch_size]))
    if not batches:
        return out

    def _do(args):
        i, items = args
        labels = _run_judge_batch(
            client, model, texts_a[i], [texts_b[j] for j, _ in items]
        )
        return i, items, labels

    with open(cache_path, "a") as fh:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(_do, b) for b in batches]
            for fut in tqdm(as_completed(futures), total=len(batches),
                            desc=f"judge {model.split('/')[-1]}", leave=False):
                try:
                    i, items, labels = fut.result()
                except Exception as e:
                    tqdm.write(f"  judge batch failed: {e}")
                    continue
                for (j, key), label in zip(items, labels):
                    score = _CONFIDENCE_TO_SCORE.get(label, 0.0)
                    out[i, j] = score
                    cache[key] = score
                    fh.write(json.dumps({
                        "key": key, "score": score, "label": label, "model": model,
                    }) + "\n")
                fh.flush()
    return out
