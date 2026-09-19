# Semantic Search over 9 Million Mathematical Theorems

**Luke Alexander, Eric Leonen, Sophie Szeto, Artemii Remizov, Ignacio Tejeda, Jarod Alper, Giovanni Inchiostro, Vasily Ilin**

[![arXiv](https://img.shields.io/badge/arXiv-2602.05216-b31b1b.svg)](https://arxiv.org/abs/2602.05216)
[![HF Paper](https://img.shields.io/badge/HF-Paper-yellow.svg)](https://huggingface.co/papers/2602.05216)
[![Dataset](https://img.shields.io/badge/Dataset-Theorem_Search-blue.svg)](https://huggingface.co/datasets/uw-math-ai/theorem-search-dataset)
[![MathGPT](https://img.shields.io/badge/MathGPT-Custom_GPT-74aa9c.svg)](https://chatgpt.com/g/g-6994f4d1eb7c8191a1a8b6aad90e1449-mathgpt)
[![Website](https://img.shields.io/badge/Website-theoremsearch.com-teal.svg)](https://theoremsearch.com)

---

<table>
<tr>
<td width="50%" valign="top">

## Overview

Mathematicians and math prover agents need fast and efficient theorem search.  
We release **[Theorem Search](https://www.theoremsearch.com/)** over all of arXiv, the Stacks Project, and six other sources.

Our search is **2× more accurate than frontier LLMs**, with only **4 second latency**.

Feedback is welcome.

---

## Retrieval Performance (Hit@10)

| Model | Theorem-level | Paper-level |
|-------|--------------:|------------:|
| Google Search | — | 0.378 |
| ChatGPT 5.2 | 0.180 | — |
| Gemini 3 Pro | 0.252 | — |
| **Ours** | **0.432** | **0.505** |

Theorem-level = retrieval of exact theorem statements  
Paper-level = retrieval of the correct paper containing the theorem

</td>

<td width="50%" valign="top">

<img src="https://github.com/user-attachments/assets/e9dd0a54-432e-4083-ba45-38a18885bd4d" width="100%" />

<br><br>

<img src="https://github.com/user-attachments/assets/089438a8-f679-4ef1-84da-bfade8d60072" width="100%" />

</td>
</tr>
</table>

---

## API

TheoremSearch provides a production REST API for semantic theorem search.**Example:**

```bash
curl https://api.theoremsearch.com/search \
  -H "Content-Type: application/json" \
  -d '{
        "query": "smooth DM stack codimension one",
        "n_results": 5
      }'
```

Returns a JSON object containing theorem-level results with metadata and similarity scores.

## MCP

TheoremSearch is also available as an MCP tool for AI agents with a single tool `theorem_search`. Endpoint: `https://api.theoremsearch.com/mcp`.

---

## Citation

```bibtex
@inproceedings{alexander2026semantic,
  title         = {Semantic Search over 9 Million Mathematical Theorems},
  author        = {Alexander, Luke and Leonen, Eric and Szeto, Sophie and Remizov, Artemii and Tejeda, Ignacio and Alper, Jarod and Inchiostro, Giovanni and Ilin, Vasily},
  booktitle     = {ICLR 2026 Workshop on Logical Reasoning of Large Language Models},
  year          = {2026},
  eprint        = {2602.05216},
  archivePrefix = {arXiv},
  primaryClass  = {cs.IR},
  url           = {https://arxiv.org/abs/2602.05216}
}

@article{kurgan2026theoremgraph,
  title         = {TheoremGraph: Bridging Formal and Informal Mathematics},
  author        = {Kurgan, Simon and Wang, Evan and Leonen, Eric and Szeto, Sophie and Alexander, Luke and Remizov, Artemii and Alper, Jarod and Inchiostro, Giovanni and Ilin, Vasily},
  journal       = {arXiv preprint arXiv:2606.25363},
  year          = {2026},
  eprint        = {2606.25363},
  archivePrefix = {arXiv},
  primaryClass  = {cs.IR},
  url           = {https://arxiv.org/abs/2606.25363}
}
```
