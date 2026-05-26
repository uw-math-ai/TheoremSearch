# Wiring an informal-dep retrieval arm into this project

This doc plans how to add a **third RAG arm** to aurasoph's existing
no-RAG / RAG / library-search comparison without modifying the
formalization, typecheck, or judging stages — only the retrieval step
changes.

The premise: aurasoph's existing graph signal is the **formal**-dep graph
(`sig`/`extends`/`field` edges from lean-graph), surfaced via a learned
linear query head over Qwen3-Embedding-8B slogans. Our alternative
signal is the **informal**-dep graph over 1.84M arXiv papers (18.3M
edges, RDS table `informal_dependency`), pre-joined to formal siblings
in `formalization_candidate_neighborhood` (14,084 rows).

## Drop-in interface contract

`scripts/build_rag_context.py` lines 38–54 are the entry point. The
existing code:

```python
q = retriever.embed(query)                # (D,)
scores = q @ corpus_emb.T / scale         # (N,)
scores[forbidden_ids] = -inf
topk = scores.argsort()[-k:][::-1]
premise_names = [id_to_decl_name[i] for i in topk]
```

A `graph_pack(nl_query, k, exclude_ids)` retriever has the same
signature: input is an NL string, output is `list[str]` of formal
decl names ranked by relevance, with `exclude_ids` honored (target +
transitive reverse-deps via lean-graph, same as the existing arm).

Replace the body, keep everything below.

## What `graph_pack` does internally

Two-hop walk: NL query → informal anchor(s) → formal sibling(s).

1. Embed `nl_query` with model `qwen3-8b` (full-corpus model; the two
   new variants `qwen3-8b-augminimal` and `qwen3-8b-lsv2slogan` are
   still backfilling — see [`schema.md`][schema] for current row
   counts).
2. ANN over `embedding` filtered to the *informal* side of the corpus
   to get top-N nearest informal anchors. Use the
   `gold_subset_i2f` pool descriptor as the candidate frame; tunable
   N (start with 5–10 anchors per query).
3. For each anchor `statement_id`, join
   `formalization_candidate_neighborhood` to collect every
   `resolved_decls` array (these are decl-names of formalized siblings
   the informal-dep graph predicts are relevant).
4. Union the resulting decl-name multiset; rank by frequency × anchor
   similarity; clip to top-`k`; apply `exclude_ids` mask.

Pseudocode (one DB round-trip per query, all set-arithmetic in
Postgres):

```python
def graph_pack(nl_query, k=10, exclude_ids=None):
    q_vec = embed_qwen3_8b(nl_query)  # (4096,)
    cur.execute("""
        WITH anchor_hits AS (
            SELECT s.statement_id,
                   1 - (e.embedding <=> %s::vector) AS sim
            FROM embedding e
            JOIN slogan s ON s.slogan_id = e.slogan_id
            JOIN informal_metadata im ON im.statement_id = s.statement_id
            WHERE e.model_name = 'qwen3-8b'
            ORDER BY e.embedding <=> %s::vector
            LIMIT 10
        ),
        graph_walk AS (
            SELECT DISTINCT
                   UNNEST(fcn.resolved_decls) AS decl_name,
                   MAX(ah.sim) AS best_anchor_sim,
                   COUNT(*) AS anchor_support
            FROM anchor_hits ah
            JOIN formalization_candidate_neighborhood fcn
              ON fcn.anchor_statement_id = ah.statement_id
            WHERE fcn.status = 'resolved'
            GROUP BY 1
        )
        SELECT decl_name
        FROM graph_walk
        WHERE decl_name <> ALL(%s::text[])  -- forbidden mask
        ORDER BY anchor_support DESC, best_anchor_sim DESC
        LIMIT %s
    """, (q_vec, q_vec, list(exclude_ids or []), k))
    return [r[0] for r in cur.fetchall()]
```

## Three-arm comparison design

Same 24 post-cutoff Mathlib v4.30 targets aurasoph already ran
(`results/large_corpus/ml30_targets.json`); same sandboxed formalizer
prompt; same typecheck + hand-judged correctness. Only retrieval
varies:

| arm | retrieval | source already exists? |
|---|---|---|
| no-RAG | none | ✓ (`ml30_norag.json`) |
| RAG (cosine + learned head) | aurasoph's `FormalRetriever.search_by_vec` | ✓ (`ml30_rag.json`) |
| **graph-pack** | informal-dep two-hop (this doc) | new — to run |
| library-search | tool-using agent | ✓ (`ml30_libsearch.json`) |

Headline question: does `graph-pack` beat or match `RAG` on hand-judged
correctness at the same N? McNemar test for pairwise significance.

Secondary: tokens-out + tool-call count per arm — graph-pack should
be the cheapest retrieval (one Postgres query, no GPU inference at
query time), so a tie on correctness is itself a finding.

## What's needed before this can run

1. **Confirm embedding model match.** The colleague's RAG arm
   currently uses `qwen3-8b` (the original, 12.2M rows in `embedding`).
   `graph-pack` should use the *same* model so the comparison is
   apples-to-apples.
2. **Forbidden mask in our retriever.** Their forbidden set is
   `{target_decl_id} ∪ transitive-reverse-deps(target)` via lean-graph.
   Convert to a `text[]` of decl-names for the SQL `<> ALL(...)` clause
   above. (lean-graph stores this; integration helper in
   `src/formal_retriever.py`.)
3. **Pilot on 3–5 queries** before the full 24 to verify the two-hop
   walk surfaces sensible decls and that `formalization_candidate_neighborhood`
   coverage is adequate for v4.30 hold-outs (the table was built
   2026-05-24 from a snapshot — verify v4.30 targets aren't in it
   under different IDs).

## Caveats / known asymmetries

- aurasoph's retriever embeds at *inference time* (their query head
  trained on lean-graph labels). `graph-pack` retrieves over
  *pre-computed* anchor embeddings. The trained head adapts the
  embedding for the retrieval task; ours doesn't. If `graph-pack`
  underperforms it could be the embedding adaptation, not the graph
  signal — control by also running `graph-pack` *with* the trained
  query head applied to the anchor side.
- `formalization_candidate_neighborhood` is currently pool
  `gold_subset_i2f` only (13k anchors). Cycle-2 may want to expand the
  candidate pool by re-joining against a larger informal-dep walk —
  see [`smoke_test_candidates.md`][stc] for the walk methodology.

[schema]: /formalized_graph/docs/paper_writing/schema.md
[stc]: /formalized_graph/docs/paper_writing/smoke_test_candidates.md
