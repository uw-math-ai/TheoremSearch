# TheoremSearch API

The main entry point is `/graph` — a small set of endpoints for navigating the corpus.

| Subroute | Use it to... |
|---|---|
| [`GET /graph/paper`](#graph-paper) | Look up a paper and its statements + dependencies. |
| [`GET /graph/statement`](#graph-statement) | Center the dependency graph on a statement and walk outward. |
| [`GET /graph/embedding`](#graph-embedding) | Semantic search by query string. |

Conventions:

- All IDs are UUIDs.
- Empty / missing fields are omitted from responses (`response_model_exclude_none=True`).
- Filter params that take lists are repeated, e.g. `?sources=arXiv&sources=Stacks Project`.

---

<a id="graph-paper"></a>
## `GET /graph/paper`

Look up a paper. Returns the paper, its statements, and its dependencies — in one shot.

A paper is either an arXiv paper, a Lean Community blueprint, a Lean repo, etc. (see `paper.kind`). Lean repos return their formal statements and `formal_dependency` edges; everything else returns informal statements and `informal_dependency` edges.

### Two ways to look it up

```http
GET /graph/paper/{paper_id}
GET /graph/paper?source=arXiv&external_id=2301.00001
```

Use the UUID form if you already have it (from `/graph/embedding` or a previous response). Use `?source=&external_id=` if you only have the external identifier (arXiv ID, repo slug, etc.).

### Query params

| Param | Type | Default | Notes |
|---|---|---|---|
| `items` | list of `paper` / `statements` / `dependencies` | all three | Which keys to populate. Repeat for multiple, e.g. `?items=paper&items=statements`. |

### Response

```jsonc
{
  "paper": {
    "paper_id": "…",
    "title": "…",
    "kind": "paper" | "lean_repo" | "blueprint" | …,
    "source": "arXiv" | "Lean Community" | "Lean Repo" | …,
    "authors": ["…"],
    "url": "…",
    "external_id": "2301.00001",
    "abstract": "…",          // arXiv only
    "repo_slug": "owner/repo", // Lean Community only
    "lean_toolchain": "v4.x",  // Lean Repo only
    // …source-specific fields
  },
  "statements": [
    {
      "statement_id": "…",
      "name": "Theorem 3.2",   // informal: kind + ref;  formal: Lean decl_name
      "formality": "informal" | "formal",
      "kind": "theorem" | "lemma" | "definition" | …,
      "body": "…",             // informal: LaTeX; formal: signature
      "proof": "…",            // informal: LaTeX; formal: tactic_summary (often null)
      "slogan": "…"            // first sufficient slogan, if any
      // …formality-specific fields (docstring, module, note, …)
    }
  ],
  "dependencies": [
    {
      "src_id": "…",
      "dep_id": "…",           // resolved target (may be null for unresolved interpaper cites)
      // informal-only:
      "cite_id": "…",          // resolved interpaper target paper
      "cite_key":  "smith2020",
      "dep_name":  "Theorem 3.2",
      "location":  "body" | "proof" | "note" | …,
      "methods":   ["deterministic" | "heuristic" | "llm" | "judge"],
      // formal-only:
      "edge_type": "sig" | "def" | "proof" | "extends" | "field" | "docref"
    }
  ]
}
```

---

<a id="graph-statement"></a>
## `GET /graph/statement/{statement_id}`

Center the dependency graph on a single statement and walk outward.

### Query params

| Param | Type | Default | Notes |
|---|---|---|---|
| `direction` | `src` / `dep` / `both` | `src` | `src`: traverse what this statement uses. `dep`: traverse what uses this statement. `both`: union. |
| `formality` | `informal` / `formal` | `informal` | Which dependency table to walk. |

### Response

```jsonc
{
  "nodes": [
    {
      "statement_id": "…",
      "name": "Theorem 3.2",   // or Lean decl_name in formal mode
      "slogan": "…",
      "depth": 0               // 0 = the origin; 1 = a direct neighbor
    }
  ],
  "edges": [
    // Same shape as /graph/paper's "dependencies" entries.
  ]
}
```

### Example

```http
GET /graph/statement/abc-…?direction=src
```

Returns the statement and its direct dependencies (one hop), along with the edges connecting them.

---

<a id="graph-embedding"></a>
## `GET /graph/embedding`

Semantic search. Embeds the query and matches against the slogan-embedding index, then reranks by full-precision cosine + optional citation boost.

### Query params

| Param | Type | Default | Notes |
|---|---|---|---|
| `query` | str | required | Natural-language query. |
| `n_results` | int, 1–100 | 10 | Final result count. |
| `sources` | list of str | — | Filter by `paper.source` (repeat for multiple). |
| `types` | list of str | — | Filter by statement kind (`theorem`, `lemma`, …). |
| `authors` | list of str | — | Substring filter on `paper.authors`. |
| `min_citations` | int, ≥0 | 0 | Lower bound on arXiv citation count. |
| `citation_weight` | float, ≥0 | 0.0 | Boost score by `citation_weight × ln(citations)`. |
| `in_journal` | bool | — | Restrict to journal-published / non-journal papers. |

### Response

```jsonc
{
  "results": [
    {
      "statement_id": "…",
      "paper_id":     "…",
      "name":         "Theorem 3.2",
      "body":         "…",
      "slogan":       "…",
      "source":       "arXiv",
      "title":        "…",
      "authors":      ["…"],
      "url":          "…",
      "external_id":  "…",
      "citation_count": 42,
      "similarity":   0.81,    // cosine similarity to the query embedding
      "score":        0.81     // similarity + citation_weight × ln(citations)
    }
  ]
}
```

### Example

```http
GET /graph/embedding?query=mean+value+theorem&types=theorem&min_citations=10&citation_weight=0.05
```

---

## Typical workflow

1. **Search**: `GET /graph/embedding?query=…` → pick a `statement_id`.
2. **Explore**: `GET /graph/statement/{statement_id}?direction=both` → see the one-hop dependency neighborhood.
3. **Drill into a paper**: `GET /graph/paper/{paper_id}` → see every statement + dependency in that paper.
