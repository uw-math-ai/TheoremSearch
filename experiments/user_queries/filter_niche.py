"""
Filter user queries by "nicheness" — keep only queries about specific, non-famous
results that web search is unlikely to handle well.

This is an INDEPENDENT pre-filter (no peeking at evaluation results), making the
subsequent evaluation non-circular.

Categories:
  NICHE    — Specific result known only to subfield experts. Keep.
  FAMOUS   — Well-known named theorem, textbook result, or famous conjecture. Drop.
  VAGUE    — Too vague to be a specific theorem (topic name, single concept). Drop.
  UNCLEAR  — Borderline. Keep (conservative).

Usage: python filter_niche.py
"""

import pandas as pd
import json
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """You classify mathematical search queries by how "niche" the result is.

NICHE — The query describes a specific mathematical result that would only be known to
experts in a narrow subfield. It is NOT a textbook result, NOT a famous named theorem,
and NOT something with extensive coverage on Wikipedia or in standard references.
Examples of NICHE:
- "Push-forward of the structure sheaf is the structure sheaf for morphism from a seminormal target with connected fibers"
- "Asymptotically optimally doubling measures with small beta2 at a scale have small beta2 at smaller scales"
- "The singular locus of the closure of BwB/B in GL_n/B includes all smaller Schubert varieties"
- "Ultrafilters where all sets have divergent series of reciprocals form a closed right ideal in beta N"
- "Every KSBA-stable pair is the stable model of a Q-stable pair"
- "Formula for the class of the zero section in a compactified universal Jacobian"

FAMOUS — The query asks about a well-known result that appears in textbooks, Wikipedia,
or is a famous named theorem/conjecture that any mathematician would recognize.
Examples of FAMOUS:
- "bounded sequence has convergent subsequence" (Bolzano-Weierstrass)
- "structure of modules over PID"
- "Tate Shafarevich group is finite" (famous conjecture)
- "Quasi-coherent sheaves satisfy descent in the fpqc topology"
- "A finitely generated k algebra has finitely many minimal primes"
- "The sum of the fibonacci numbers"
- "every 3-manifold admits a foliation"
- "Matrix-vector multiplication distributes over the terms in a finite sum of vectors"

VAGUE — The query is too vague, just names a topic, or doesn't describe a specific
mathematical claim/result.
Examples of VAGUE:
- "Restriction operator, invariant, paranormal"
- "betti numbers on cubical complexes"
- "deformations of complex parallelisable manifolds"
- "theta correspondence of associate cycle"
- "m primary monomial ideals glicciness"

When in doubt between NICHE and FAMOUS, ask: "Would a graduate student in the relevant
subfield know this off the top of their head?" If yes → FAMOUS. If they'd need to look
it up in a specific paper → NICHE.

When in doubt between NICHE and VAGUE, ask: "Does the query describe a specific claim
or property?" If yes → NICHE. If it's just naming a topic → VAGUE."""

BATCH_SIZE = 40


def classify_batch(queries):
    batch_str = "\n".join(f"{i}. {q}" for i, q in enumerate(queries))

    prompt = f"""Classify each query below as NICHE, FAMOUS, or VAGUE.
Return a JSON object where keys are index numbers (as strings) and values are the classification.
Example: {{"0": "NICHE", "1": "FAMOUS", "2": "VAGUE"}}

{batch_str}"""

    response = client.chat.completions.create(
        model="gpt-5.4-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )

    text = response.choices[0].message.content
    parsed = json.loads(text)

    # Handle nested response format
    if isinstance(parsed, dict):
        list_val = next((v for v in parsed.values() if isinstance(v, list)), None)
        if list_val:
            result = {}
            for item in list_val:
                if isinstance(item, dict) and "i" in item and "v" in item:
                    result[str(item["i"])] = item["v"]
            return result
        # Direct format: {"0": "NICHE", "1": "FAMOUS", ...}
        return {k: v for k, v in parsed.items() if k.isdigit()}
    return {}


def main():
    df = pd.read_csv("filtered_queries.csv")
    queries = df["query"].tolist()
    print(f"Total queries: {len(queries)}")

    all_classifications = {}

    for batch_start in range(0, len(queries), BATCH_SIZE):
        batch = queries[batch_start:batch_start + BATCH_SIZE]
        print(f"  Classifying {batch_start}-{batch_start + len(batch) - 1}...", end=" ", flush=True)

        try:
            result = classify_batch(batch)
            for k, v in result.items():
                all_classifications[batch_start + int(k)] = v
            counts = {"NICHE": 0, "FAMOUS": 0, "VAGUE": 0}
            for v in result.values():
                counts[v] = counts.get(v, 0) + 1
            print(f"N={counts.get('NICHE',0)} F={counts.get('FAMOUS',0)} V={counts.get('VAGUE',0)}")
        except Exception as e:
            print(f"ERROR: {e}")

    # Summary
    from collections import Counter
    counts = Counter(all_classifications.values())
    print(f"\n--- Classification Summary ---")
    for label in ["NICHE", "FAMOUS", "VAGUE"]:
        print(f"  {label}: {counts.get(label, 0)}")
    print(f"  Unclassified: {len(queries) - len(all_classifications)}")

    # Save classifications
    classified = []
    for i, q in enumerate(queries):
        classified.append({
            "index": i,
            "query": q,
            "nicheness": all_classifications.get(i, "UNCLASSIFIED"),
        })

    with open("query_nicheness.json", "w") as f:
        json.dump(classified, f, indent=2)

    # Save niche-only queries
    niche_indices = [i for i, c in all_classifications.items() if c == "NICHE"]
    df_niche = df.iloc[niche_indices].copy()
    df_niche.to_csv("niche_queries.csv", index=False)
    print(f"\nNiche queries saved: {len(df_niche)} to niche_queries.csv")

    # Print examples of each category
    for label in ["NICHE", "FAMOUS", "VAGUE"]:
        examples = [queries[i] for i, c in all_classifications.items() if c == label][:8]
        print(f"\n--- {label} examples ---")
        for q in examples:
            print(f"  {q[:100]}")


if __name__ == "__main__":
    main()
