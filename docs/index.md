---
layout: default
title: TheoremSearch
---

# Semantic Search over 9 Million Mathematical Theorems

**[Luke Alexander](https://www.linkedin.com/in/lukealexanderluke/), [Eric Leonen](https://github.com/ericleonen), [Sophie Szeto](https://www.linkedin.com/in/sophie-szeto/), [Artemii Remizov](https://www.linkedin.com/in/artemii-remizov-62783631b/), [Ignacio Tejeda](https://www.ignaciotejeda.com/), [Giovanni Inchiostro](https://sites.math.washington.edu/~ginchios/), [Vasily Ilin](https://vilin97.github.io/)**

[![arXiv](https://img.shields.io/badge/arXiv-2602.05216-b31b1b.svg)](https://arxiv.org/abs/2602.05216)
[![HF Paper](https://img.shields.io/badge/HF-Paper-yellow.svg)](https://huggingface.co/papers/2602.05216)
[![Dataset](https://img.shields.io/badge/Dataset-Theorem_Search-blue.svg)](https://huggingface.co/datasets/uw-math-ai/theorem-search-dataset)
[![Demo](https://img.shields.io/badge/Demo-Live-green.svg)](https://huggingface.co/spaces/uw-math-ai/theorem-search)
[![API](https://img.shields.io/badge/API-REST-orange.svg)](https://api.theoremsearch.com/search)
[![MCP](https://img.shields.io/badge/MCP-Tool-purple.svg)](https://api.theoremsearch.com/mcp)

<table>
<tr>
<td width="50%"><img src="https://github.com/user-attachments/assets/e9dd0a54-432e-4083-ba45-38a18885bd4d" width="100%" /></td>
<td width="50%"><img src="https://github.com/user-attachments/assets/089438a8-f679-4ef1-84da-bfade8d60072" width="100%" /></td>
</tr>
</table>

## Overview

We release **Theorem Search** ([paper](https://huggingface.co/papers/2602.05216), [dataset](https://huggingface.co/datasets/uw-math-ai/theorem-search-dataset)) over all of arXiv, the Stacks Project, and six other sources. Our search is **70% more accurate than LLM search**, with only **5 second latency**.

<p style="text-align: center; margin: 2em 0;">
  <a href="https://huggingface.co/spaces/uw-math-ai/theorem-search" style="display: inline-block; padding: 12px 32px; background-color: #2563eb; color: white; text-decoration: none; border-radius: 8px; font-size: 1.2em; font-weight: bold;">Try TheoremSearch</a>
</p>

<table>
<tr>
<td width="50%" valign="top">

<h3>Retrieval Performance (Hit@10)</h3>

<table>
<tr><th>Model</th><th>Theorem-level</th><th>Paper-level</th></tr>
<tr><td>Google Search</td><td>—</td><td>0.378</td></tr>
<tr><td>ChatGPT 5.2</td><td>0.180</td><td>—</td></tr>
<tr><td>Gemini 3 Pro</td><td>0.252</td><td>—</td></tr>
<tr><td><strong>Ours</strong></td><td><strong>0.432</strong></td><td><strong>0.505</strong></td></tr>
</table>

<p><small>Theorem-level = retrieval of exact theorem statements<br/>
Paper-level = retrieval of the correct paper containing the theorem</small></p>

</td>
<td width="50%" valign="top">

<h3>Data Sources</h3>

<table>
<tr><th>Source</th><th>Theorems</th></tr>
<tr><td>arXiv</td><td>9,246,761</td></tr>
<tr><td>ProofWiki</td><td>23,871</td></tr>
<tr><td>Stacks Project</td><td>12,693</td></tr>
<tr><td>Open Logic Project</td><td>745</td></tr>
<tr><td>CRing Project</td><td>546</td></tr>
<tr><td>Stacks and Moduli</td><td>506</td></tr>
<tr><td>HoTT Book</td><td>382</td></tr>
<tr><td>An Infinitely Large Napkin</td><td>231</td></tr>
</table>

</td>
</tr>
</table>


## Motivation

Mathematical knowledge is scattered across millions of papers. Important results hide as lemmas in obscure sources, and existing search tools only operate at the document level.

**For mathematicians**, important results hide as lemmas in obscure papers, and existing tools only search at the document level. The recent AI "breakthroughs" on [Erdos problems](https://www.erdosproblems.com/) illustrate this: most turned out to be rediscoveries of results already in the literature. As [Tao observed](https://terrytao.wordpress.com/2025/11/05/mathematical-exploration-and-discovery-at-scale/), many "open" problems are open through obscurity, not difficulty. [DeepMind's Aletheia](https://arxiv.org/abs/2602.10177) confirmed this — most of its correct solutions were identifications of existing literature.

**For AI agents**, the bottleneck is the same. Without the relevant literature, LLMs confabulate incorrect arguments. In our experiments, Claude answered a research-level algebraic geometry question incorrectly on its own, but correctly when given access to TheoremSearch as a RAG tool.

## How It Works

1. **Parse theorems.** We extract over 9 million theorem statements from LaTeX sources across arXiv and seven other sources using a combination of plasTeX, TeX logging, and regex-based parsing.
2. **Generate slogans.** Each theorem is summarized into a concise natural-language description ("slogan") by DeepSeek V3, converting formal LaTeX notation into searchable English text.
3. **Embed and index.** Slogans are embedded using Qwen3-Embedding-8B and stored in a PostgreSQL database with pgvector, using an HNSW index with binary quantization for fast approximate nearest-neighbor search.
4. **Retrieve.** User queries are embedded with the same model. We retrieve the top-k theorems by Hamming distance, then re-rank by cosine similarity.


## API

TheoremSearch provides a production REST API for semantic theorem search.**Example:**

```bash
curl https://api.theoremsearch.com/search \
  -H "Content-Type: application/json" \
  -d '{"query": "smooth DM stack codimension one", "n_results": 5}'
```

Returns a JSON object containing theorem-level results with metadata and similarity scores.

## MCP

TheoremSearch is also available as an MCP tool for AI agents with a single tool `theorem_search`. Endpoint: `https://api.theoremsearch.com/mcp`.


## Citation

```bibtex
@article{alexander2026semantic,
  title  = {Semantic Search over 9 Million Mathematical Theorems},
  author = {Alexander, Luke and Leonen, Eric and Szeto, Sophie and Remizov, Artemii and Tejeda, Ignacio and Inchiostro, Giovanni and Ilin, Vasily},
  journal= {arXiv preprint arXiv:2602.05216},
  year   = {2026},
  doi    = {10.48550/arXiv.2602.05216},
  url    = {https://arxiv.org/abs/2602.05216}
}
```

## Acknowledgements

We thank the [UW eScience Institute](https://escience.washington.edu/) for supporting this project. We thank [Nebius](https://nebius.com/) for providing inference infrastructure — our demo uses [Nebius Token Factory](https://tokenfactory.nebius.com/) for fast, low-cost query embedding with [Qwen3-Embedding-8B](https://tokenfactory.nebius.com/models?search=emb&model-id=Qwen/Qwen3-Embedding-8B).

## Contact

Feedback is welcome! For questions or collaboration inquiries, reach out to [vilin@uw.edu](mailto:vilin@uw.edu).

TheoremSearch is a project of the [UW Math AI Lab](https://github.com/uw-math-ai).
