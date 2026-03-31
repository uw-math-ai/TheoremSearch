"""
LLM-as-a-judge eval on NICHE user queries.
Same design as eval_scaled.py but on niche-filtered production queries.

Usage: python eval_niche_users.py [--n 50]
"""

import json
import requests
import random
import os
import time
import statistics
import collections
import argparse
import pandas as pd
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

# --- Tool definition ---
THEOREMSEARCH_TOOL = {
    "type": "function",
    "name": "theorem_search",
    "description": (
        "Semantic search over 9.2M mathematical theorem statements from arXiv. "
        "This is NOT a keyword search engine — it matches against natural-language "
        "summaries ('slogans') of theorems. Your query MUST be a complete mathematical "
        "claim or statement, NOT a list of keywords.\n\n"
        "GOOD queries (specific claims):\n"
        "- 'The modular envelope of the cyclic associative operad is isomorphic to the open TFT modular operad'\n"
        "- 'A proper surjective morphism with connected fibers from a reduced source to a seminormal target satisfies pushforward of structure sheaf equals structure sheaf'\n"
        "- 'The semistable locus with respect to a line bundle admits a good moduli space which is a quasi-projective scheme'\n"
        "- 'Complete regular local rings are classified by prisms inside a power series ring over the Cohen ring'\n\n"
        "BAD queries (keyword soup — will return irrelevant results):\n"
        "- 'Deligne-Mumford locus open substack good moduli space semistable locus line bundle'\n"
        "- 'Feynman transform associative cyclic operad modular operads'\n"
        "- 'Baily-Borel compactification Enriques surfaces boundary components'\n\n"
        "Think: 'What would a one-sentence informal summary of this theorem sound like?'"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "A complete mathematical claim stated as a natural-language sentence. "
                    "Write it as if you were explaining the result to a colleague: "
                    "'For X satisfying Y, Z holds.' Do NOT use keyword lists."
                ),
            },
            "n_results": {
                "type": "integer",
                "description": "Number of results to return (default 20, max 25)",
                "default": 20,
            },
        },
        "required": ["query"],
    },
}

SYSTEM_PROMPT = """You are a research mathematician's assistant. Given a mathematical query,
find the most relevant theorems and cite specific results with paper references.

Provide:
1. The most relevant theorem(s) that address the query, with full statements
2. Paper titles and arXiv links
3. Brief explanation of how they relate to the query

Be precise and cite specific theorem numbers when possible."""

TOOL_ADDENDUM = """

You have access to a theorem_search tool that performs SEMANTIC SEARCH over 9.2M
mathematical theorems from arXiv. It can find specific lemmas and technical results
deep inside papers that web search cannot surface.

HOW TO USE theorem_search:
- It is NOT a keyword search engine. It matches against natural-language summaries of theorems.
- Your query MUST be a complete mathematical claim, as if stating the result to a colleague.
- GOOD: "A proper surjective morphism with connected fibers to a seminormal target satisfies
  pushforward of structure sheaf equals structure sheaf"
- BAD: "seminormal pushforward structure sheaf connected fibers"
- You can call it multiple times with different claim-style phrasings.

IMPORTANT — how to integrate results:
1. FIRST, use web search to find results and form your answer.
2. THEN, call theorem_search to see if it has a more specific or precise result.
3. Only REPLACE or AUGMENT your web search answer with theorem_search results if they
   are CLEARLY relevant to the query — i.e., the theorem statement directly addresses
   the mathematical claim in the query.
4. If theorem_search results are vague, tangential, or from a different area of math,
   IGNORE them entirely and keep your web-search-based answer.
5. Never degrade a good answer by forcing in irrelevant theorem_search results."""


TEST_QUERIES = [
    # Confirmed: TS finds "Theorem 3.11: modular operad OTFT is canonically isomorphic to modular closure of cyclic associative operad"
    # with query "modular closure of the associative cyclic operad"
    "Feynmann transform of Associative cyclic operad and modular operads",
    # Confirmed: TS finds "Corollary 3.5.2: semistable locus... adequate moduli space over projective quotient scheme"
    # with query "semistable locus admits a good moduli space which is a quasi-projective scheme"
    "Deligne-Mumford open in a stack with a good moduli space agrees with the semistable locus of a line bundle",
    # Confirmed: TS finds "Proposition 7.5 (Scattone): boundary of Baily-Borel compactification of quartic surfaces"
    # with query "type IV domain signature 2 10 Enriques lattice Baily-Borel"
    "The baily borel compactification of the modul space of Enriques surfaces",
]


def select_queries(n=50):
    """Select niche user queries, 8-30 words, shuffled."""
    df = pd.read_csv("niche_queries.csv")
    df["wc"] = df["query"].str.split().str.len()
    df = df[(df["wc"] >= 8) & (df["wc"] <= 30)].copy()
    if len(df) > n:
        random.seed(42)
        df = df.sample(n, random_state=42)
    return df["query"].tolist()


def call_theoremsearch(query, n_results=20):
    resp = requests.post(
        "https://api.theoremsearch.com/search",
        headers={"Content-Type": "application/json"},
        json={"query": query, "n_results": n_results},
        timeout=30,
    )
    resp.raise_for_status()
    theorems = resp.json().get("theorems", [])
    results = []
    for t in theorems:
        entry = {}
        for k in ("name", "slogan", "paper_title", "arxiv_id"):
            if t.get(k):
                entry[k] = t[k]
        if t.get("body"):
            entry["body"] = t["body"][:500]
        results.append(entry)
    return json.dumps(results)


def run_without_tool(query):
    t0 = time.time()
    response = client.responses.create(
        model="gpt-5.2",
        instructions=SYSTEM_PROMPT,
        input=f"Query: {query}",
        tools=[{"type": "web_search_preview"}],
    )
    return response.output_text, time.time() - t0


def run_with_tool(query):
    t0 = time.time()
    tool_calls = []

    response = client.responses.create(
        model="gpt-5.2",
        instructions=SYSTEM_PROMPT + TOOL_ADDENDUM,
        input=f"Query: {query}",
        tools=[{"type": "web_search_preview"}, THEOREMSEARCH_TOOL],
    )

    for _ in range(10):
        function_calls = [item for item in response.output if item.type == "function_call"]
        if not function_calls:
            break

        tool_results = []
        for fc in function_calls:
            args = json.loads(fc.arguments)
            ts_query = args.get("query", query)
            n_res = args.get("n_results", 20)
            tool_calls.append(ts_query)
            try:
                result = call_theoremsearch(ts_query, n_res)
            except Exception as e:
                result = json.dumps({"error": str(e)})
            tool_results.append({
                "type": "function_call_output",
                "call_id": fc.call_id,
                "output": result,
            })

        response = client.responses.create(
            model="gpt-5.2",
            instructions=SYSTEM_PROMPT + TOOL_ADDENDUM,
            input=tool_results,
            tools=[{"type": "web_search_preview"}, THEOREMSEARCH_TOOL],
            previous_response_id=response.id,
        )

    return response.output_text, time.time() - t0, tool_calls


def judge(query, resp_without, resp_with):
    if random.random() < 0.5:
        first, second = resp_without[:7000], resp_with[:7000]
        swapped = False
    else:
        first, second = resp_with[:7000], resp_without[:7000]
        swapped = True

    prompt = f"""You are an expert judge evaluating two responses to a mathematical research query.

QUERY: {query}

=== RESPONSE A ===
{first}

=== RESPONSE B ===
{second}

Which response would be MORE USEFUL to a research mathematician looking for this result?

Evaluate on:
1. CORRECTNESS: Does the response cite a theorem that actually matches the query's mathematical claim?
2. SPECIFICITY: Does it give a precise theorem statement (not just a vague description)?
3. CITATIONS: Does it provide verifiable references (paper title, arXiv ID, theorem number)?
4. RELEVANCE: How directly does the cited result address the query vs being tangentially related?

Answer with ONLY a JSON object:
{{"winner": "A" or "B" or "TIE", "score_A": <1-5>, "score_B": <1-5>, "reason": "<brief explanation>"}}"""

    response = client.chat.completions.create(
        model="gpt-5.4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"},
    )

    try:
        parsed = json.loads(response.choices[0].message.content)
    except json.JSONDecodeError:
        parsed = {"winner": "PARSE_ERROR", "score_A": 0, "score_B": 0, "reason": "parse error"}

    winner = parsed.get("winner", "PARSE_ERROR")
    score_a = parsed.get("score_A", None)
    score_b = parsed.get("score_B", None)

    if swapped:
        if winner == "A": winner = "B"
        elif winner == "B": winner = "A"
        score_a, score_b = score_b, score_a

    return {
        "winner": winner,
        "score_without": score_a,
        "score_with": score_b,
        "reason": parsed.get("reason", ""),
    }


def process_query(qi, query, total):
    tprint(f"[{qi+1}/{total}] {query[:70]}...")

    try:
        resp_without, lat_without = run_without_tool(query)
    except Exception as e:
        tprint(f"  ERROR (without): {e}")
        resp_without, lat_without = f"ERROR: {e}", 0

    try:
        resp_with, lat_with, tool_calls = run_with_tool(query)
    except Exception as e:
        tprint(f"  ERROR (with): {e}")
        resp_with, lat_with, tool_calls = f"ERROR: {e}", 0, []

    try:
        judgment = judge(query, resp_without, resp_with)
    except Exception as e:
        tprint(f"  ERROR (judge): {e}")
        judgment = {"winner": "ERROR", "score_without": None, "score_with": None, "reason": str(e)}

    winner_label = {"A": "WITHOUT", "B": "  WITH", "TIE": "   TIE"}.get(judgment["winner"], " ERROR")
    tprint(f"  {winner_label} | {judgment['score_without']}->{judgment['score_with']} | {len(tool_calls)} calls | {lat_without:.0f}s/{lat_with:.0f}s")

    return {
        "query": query,
        "response_without": resp_without,
        "response_with": resp_with,
        "tool_calls": tool_calls,
        "judgment": judgment,
        "latency": {"without_tool": lat_without, "with_tool": lat_with},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=50)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--test", action="store_true", help="Run on 3 test queries where TS can find results")
    args = parser.parse_args()

    QUERIES = TEST_QUERIES if args.test else select_queries(args.n)
    print(f"Niche user query evaluation: {len(QUERIES)} queries")
    print(f"GPT 5.2 (web only) vs GPT 5.2 (web + TheoremSearch tool)")
    print(f"Judge: GPT-5.4 via API")
    print(f"Workers: {args.workers}")
    print()

    all_results = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(process_query, i, q, len(QUERIES)): i
            for i, q in enumerate(QUERIES)
        }
        for future in as_completed(futures):
            try:
                result = future.result()
                all_results.append(result)
            except Exception as e:
                tprint(f"  FATAL ERROR: {e}")

    all_results.sort(key=lambda r: QUERIES.index(r["query"]))

    with open("eval_niche_users_results.json", "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    # --- Summary ---
    valid = [r for r in all_results if r["judgment"]["winner"] not in ("ERROR", "PARSE_ERROR")]

    print(f"\n\n{'='*70}")
    print(f"NICHE USER QUERY EVALUATION ({len(valid)} valid of {len(all_results)} total)")
    print(f"{'='*70}")

    # Win rate
    with_wins = sum(1 for r in valid if r["judgment"]["winner"] == "B")
    without_wins = sum(1 for r in valid if r["judgment"]["winner"] == "A")
    ties = sum(1 for r in valid if r["judgment"]["winner"] == "TIE")
    n = len(valid)
    print(f"\n--- Win Rate ---")
    print(f"TheoremSearch helps:    {with_wins}/{n} ({100*with_wins/n:.0f}%)")
    print(f"Better without:         {without_wins}/{n} ({100*without_wins/n:.0f}%)")
    print(f"Tie:                    {ties}/{n} ({100*ties/n:.0f}%)")

    # Scores
    sw = [r["judgment"]["score_without"] for r in valid if r["judgment"]["score_without"] is not None]
    sc = [r["judgment"]["score_with"] for r in valid if r["judgment"]["score_with"] is not None]
    if sw and sc:
        print(f"\n--- Average Quality Score (1-5) ---")
        print(f"Without TheoremSearch: {statistics.mean(sw):.2f}")
        print(f"With TheoremSearch:    {statistics.mean(sc):.2f}")
        delta = statistics.mean(sc) - statistics.mean(sw)
        print(f"Delta:                 {'+' if delta >= 0 else ''}{delta:.2f}")

    # Score distributions
    print(f"\n--- Score Distribution ---")
    print(f"{'Score':<8} {'Without':>10} {'With':>10}")
    for s in range(1, 6):
        nw = sum(1 for x in sw if x == s)
        nc = sum(1 for x in sc if x == s)
        print(f"{s:<8} {nw:>10} {nc:>10}")

    # Rescue rate
    useless = [r for r in valid if (r["judgment"].get("score_without") or 0) <= 2]
    rescued = [r for r in useless if (r["judgment"].get("score_with") or 0) >= 4]
    if useless:
        print(f"\n--- Rescue Rate ---")
        print(f"Queries where web fails (score ≤ 2): {len(useless)}")
        print(f"Rescued to useful (score ≥ 4):       {len(rescued)} ({100*len(rescued)/len(useless):.0f}%)")

    # Oracle
    oracle = [max(r["judgment"].get("score_without", 0), r["judgment"].get("score_with", 0)) for r in valid]
    baseline = [r["judgment"].get("score_without", 0) for r in valid]
    with_scores = [r["judgment"].get("score_with", 0) for r in valid]
    print(f"\n--- Oracle (best of both) ---")
    print(f"Avg baseline:  {statistics.mean(baseline):.2f}")
    print(f"Avg with tool: {statistics.mean(with_scores):.2f}")
    print(f"Avg oracle:    {statistics.mean(oracle):.2f} (+{statistics.mean(oracle)-statistics.mean(baseline):.2f} over baseline)")

    # Tool usage
    tc_counts = [len(r["tool_calls"]) for r in valid]
    print(f"\n--- Tool Usage ---")
    print(f"Avg calls per query: {statistics.mean(tc_counts):.1f}")

    # Stratified by baseline score
    print(f"\n--- Stratified by Baseline Score ---")
    print(f"{'Baseline':<12} {'N':>4} {'TS wins':>10} {'Win%':>6} {'Avg Δ':>8}")
    for thresh in range(1, 6):
        group = [r for r in valid if r["judgment"].get("score_without") == thresh]
        if not group:
            continue
        w = sum(1 for r in group if r["judgment"]["winner"] == "B")
        avg_d = statistics.mean(
            (r["judgment"].get("score_with") or 0) - (r["judgment"].get("score_without") or 0)
            for r in group
        )
        print(f"   {thresh:<9} {len(group):>4} {w:>7}/{len(group):<3} {100*w/len(group):>5.0f}% {avg_d:>+7.2f}")

    print(f"\nFull results saved to eval_niche_users_results.json")
