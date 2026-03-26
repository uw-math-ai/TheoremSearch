"""
Query augmentation experiment on the validation set.

Compares Hit@1/10/20 and MRR@20 for:
  1. Raw queries (baseline)
  2. LLM-augmented queries (treatment)

Usage: python eval_query_augmentation.py [--augment] [--k 20]
"""

import json
import requests
import os
import re
import time
import argparse
import statistics
from datasets import load_dataset
from openai import OpenAI
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

print_lock = threading.Lock()
def tprint(msg):
    with print_lock:
        print(msg, flush=True)


def extract_arxiv_id(url):
    """Extract arXiv ID from URL like https://arxiv.org/abs/2310.15076"""
    m = re.search(r'(\d{4}\.\d{4,5})', url)
    return m.group(1) if m else None


EMBED_PROMPT = "Instruct: Given a math search query, retrieve theorems mathematically equivalent to the query.\nQuery: "


def search_theoremsearch(query, n_results=20, use_prompt=False):
    search_query = EMBED_PROMPT + query if use_prompt else query
    resp = requests.post(
        "https://api.theoremsearch.com/search",
        headers={"Content-Type": "application/json"},
        json={"query": search_query, "n_results": n_results, "sources": ["arXiv"]},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("theorems", [])


AUGMENT_PROMPT = """You are helping a mathematician search for a specific theorem in a large corpus.
The user has a query describing a mathematical result. Your job is to rewrite it as a
clear, complete, natural-language statement of the theorem — the kind of one-sentence
summary that would appear in a survey or textbook.

Rules:
- Output ONLY the rewritten query, nothing else.
- State the result as a complete mathematical claim: "For X satisfying Y, Z holds."
- Expand abbreviations and fill in implicit context where possible.
- Do NOT add information you're not confident about — just clarify what's already there.
- Keep it to 1-2 sentences.

Examples:

Input: "Smooth DM stack is uniquely determined by codimension one behaviour"
Output: "A smooth separated tame Deligne-Mumford stack is uniquely determined up to isomorphism by its restriction to the complement of a codimension-two closed subset."

Input: "Push-forward of the structure sheaf is the structure sheaf for morphism from a seminormal target with connected fibers"
Output: "For a proper surjective morphism with connected fibers from a reduced scheme to a seminormal target, the pushforward of the structure sheaf is the structure sheaf of the target."

Input: "bounded sequence has convergent subsequence"
Output: "Every bounded sequence in a finite-dimensional real normed space has a convergent subsequence."
"""


def augment_query(query):
    """Use LLM to rewrite query as a precise claim-style statement."""
    response = client.chat.completions.create(
        model="gpt-5.4-mini",
        messages=[
            {"role": "system", "content": AUGMENT_PROMPT},
            {"role": "user", "content": query},
        ],
        temperature=0,
        max_completion_tokens=200,
    )
    return response.choices[0].message.content.strip().strip('"')


def evaluate_query(query, ground_truth_arxiv_id, ground_truth_theorem, k=20, use_prompt=False):
    """Search and check if ground truth appears in top-k results."""
    try:
        results = search_theoremsearch(query, n_results=k, use_prompt=use_prompt)
    except Exception as e:
        return {"hits": [{"paper_hit": False, "theorem_hit": False}] * k, "first_hit_rank": None, "results": [], "error": str(e)}

    hits = []
    first_hit_rank = None

    for i, r in enumerate(results):
        paper = r.get("paper", {})
        paper_id = paper.get("paper_id", "") if isinstance(paper, dict) else ""
        # Strip version suffix (e.g., "2310.15076v2" -> "2310.15076")
        paper_id_clean = re.sub(r'v\d+$', '', paper_id)

        # Match on arXiv ID (paper-level match)
        is_hit = (paper_id_clean == ground_truth_arxiv_id)

        # Also try theorem-level match (name matches)
        thm_name = r.get("name", "")
        is_theorem_hit = is_hit and (
            thm_name.lower().strip() == ground_truth_theorem.lower().strip()
        )

        hits.append({"paper_hit": is_hit, "theorem_hit": is_theorem_hit})
        if is_hit and first_hit_rank is None:
            first_hit_rank = i + 1  # 1-indexed

    return {
        "hits": hits,
        "first_hit_rank": first_hit_rank,
        "results": [
            {
                "name": r.get("name", ""),
                "slogan": r.get("slogan", "")[:150],
                "paper_id": r.get("paper", {}).get("paper_id", "") if isinstance(r.get("paper"), dict) else "",
                "similarity": r.get("similarity", 0),
            }
            for r in results[:k]
        ],
    }


def compute_metrics(eval_results, k_values=[1, 10, 20]):
    """Compute Hit@k and MRR@k from evaluation results."""
    metrics = {}
    n = len(eval_results)

    for k in k_values:
        hits = 0
        for r in eval_results:
            paper_hits = [h["paper_hit"] for h in r["eval"]["hits"][:k]]
            if any(paper_hits):
                hits += 1
        metrics[f"Hit@{k}"] = hits / n

    # MRR@20
    rr_sum = 0
    for r in eval_results:
        rank = r["eval"]["first_hit_rank"]
        if rank is not None and rank <= 20:
            rr_sum += 1.0 / rank
    metrics["MRR@20"] = rr_sum / n

    # Theorem-level metrics
    for k in k_values:
        hits = 0
        for r in eval_results:
            thm_hits = [h["theorem_hit"] for h in r["eval"]["hits"][:k]]
            if any(thm_hits):
                hits += 1
        metrics[f"Thm_Hit@{k}"] = hits / n

    return metrics


def process_one(i, record, augment, k, total, use_prompt=False):
    query = record["query"]
    arxiv_id = extract_arxiv_id(record["link to paper on arxiv"])
    theorem = record["theorem number"]

    if augment:
        try:
            augmented = augment_query(query)
        except Exception as e:
            tprint(f"  [{i+1}/{total}] AUGMENT ERROR: {e}")
            augmented = query
        search_query = augmented
    else:
        augmented = None
        search_query = query

    eval_result = evaluate_query(search_query, arxiv_id, theorem, k, use_prompt=use_prompt)

    hit_at_1 = any(h["paper_hit"] for h in eval_result["hits"][:1])
    hit_at_20 = any(h["paper_hit"] for h in eval_result["hits"][:20])
    rank = eval_result["first_hit_rank"]
    rank_str = str(rank) if rank else "—"

    tprint(f"  [{i+1}/{total}] {'✓' if hit_at_20 else '✗'} rank={rank_str:>3} | {query[:60]}")
    if augmented and augmented != query:
        tprint(f"           → {augmented[:60]}")

    return {
        "query": query,
        "augmented_query": augmented,
        "arxiv_id": arxiv_id,
        "theorem": theorem,
        "paper_title": record["paper title"],
        "eval": eval_result,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--augment", action="store_true")
    parser.add_argument("--prompt", action="store_true", help="Prepend instruction prompt to query embedding")
    parser.add_argument("--k", type=int, default=20)
    parser.add_argument("--workers", type=int, default=5)
    args = parser.parse_args()

    ds = load_dataset("uw-math-ai/theorem-search-dataset", "theorem-test")
    records = list(ds["train"])

    parts = []
    if args.prompt:
        parts.append("PROMPTED")
    if args.augment:
        parts.append("AUGMENTED")
    mode = "+".join(parts) if parts else "BASELINE"
    print(f"Query Augmentation Experiment — {mode}")
    print(f"Queries: {len(records)}, k={args.k}")
    print()

    all_results = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(process_one, i, r, args.augment, args.k, len(records), args.prompt): i
            for i, r in enumerate(records)
        }
        for future in as_completed(futures):
            try:
                all_results.append(future.result())
            except Exception as e:
                tprint(f"  FATAL: {e}")

    all_results.sort(key=lambda r: [rec["query"] for rec in records].index(r["query"]))

    # Compute metrics
    metrics = compute_metrics(all_results)

    print(f"\n{'='*60}")
    print(f"RESULTS — {mode}")
    print(f"{'='*60}")
    print(f"\n{'Metric':<15} {'Value':>8}")
    print(f"{'-'*25}")
    for k, v in metrics.items():
        print(f"{k:<15} {v:>8.3f}")

    # Save
    outfile = f"eval_augmentation_{mode.lower().replace('+', '_')}.json"
    with open(outfile, "w") as f:
        json.dump({"mode": mode, "metrics": metrics, "results": all_results}, f, indent=2, default=str)
    print(f"\nSaved to {outfile}")
