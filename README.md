# Semantic Search over 9 Million Mathematical Theorems

**Luke Alexander, Eric Leonen, Sophie Szeto, Artemii Remizov, Ignacio Tejeda, Giovanni Inchiostro, Vasily Ilin**

[![arXiv](https://img.shields.io/badge/arXiv-2602.05216-b31b1b.svg)](https://arxiv.org/abs/2602.05216)
[![HF Paper](https://img.shields.io/badge/HF-Paper-yellow.svg)](https://huggingface.co/papers/2602.05216)
[![Dataset](https://img.shields.io/badge/Dataset-Theorem_Search-blue.svg)](https://huggingface.co/datasets/uw-math-ai/theorem-search-dataset)
[![Demo](https://img.shields.io/badge/Demo-Live-green.svg)](https://huggingface.co/spaces/uw-math-ai/theorem-search)

---

<table>
<tr>
<td width="60%" valign="top">

## Overview

Mathematicians and math prover agents need fast and efficient theorem search.  
We release **[Theorem Search](https://huggingface.co/spaces/uw-math-ai/theorem-search)** over all of arXiv, the Stacks Project, and six other sources.

Our search is **2× more accurate than frontier LLMs**, with only **4 second latency**.

Feedback is welcome.

---

## Retrieval Performance (Hit@10)

| Model | Hit@10 |
|------|--------|
| Google Search | <span style="color:red">0.378</span> |
| Chat-GPT 5.2 | <span style="color:blue">0.180</span> |
| Gemini 3 Pro | <span style="color:blue">0.252</span> |
| **Ours** | **<span style="color:blue">0.432</span> / <span style="color:red">0.505</span>** |

<span style="color:blue">Blue</span>: theorem-level results  
<span style="color:red">Red</span>: paper-level results  

</td>

<td width="40%" valign="top">

<img src="https://github.com/user-attachments/assets/e9dd0a54-432e-4083-ba45-38a18885bd4d" width="100%" />

<br><br>

<img src="https://github.com/user-attachments/assets/089438a8-f679-4ef1-84da-bfade8d60072" width="100%" />

</td>
</tr>
</table>

---

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
