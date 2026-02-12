<div align="center">

# Semantic Search over 9 Million Mathematical Theorems

**Luke Alexander, Eric Leonen, Sophie Szeto, Artemii Remizov, Ignacio Tejeda, Giovanni Inchiostro, Vasily Ilin**

[![arXiv](https://img.shields.io/badge/arXiv-2602.05216-b31b1b.svg)](https://arxiv.org/abs/2602.05216)
[![HF Paper](https://img.shields.io/badge/HF-Paper-yellow.svg)](https://huggingface.co/papers/2602.05216)
[![Dataset](https://img.shields.io/badge/Dataset-Theorem_Search-blue.svg)](https://huggingface.co/datasets/uw-math-ai/theorem-search-dataset)
[![Demo](https://img.shields.io/badge/Demo-Live-green.svg)](https://huggingface.co/spaces/uw-math-ai/theorem-search)

</div>


---

## Overview

Mathematical knowledge is expressed in discrete statements — *theorems, lemmas, propositions, corollaries*.  
Existing search engines operate at the **paper level**.

We build:

- A unified corpus of **9.2 million human-authored theorem statements**
- A **theorem-level semantic search engine**
- An embedding setup that supports natural language and mathematical notation

This enables precise retrieval of mathematical statements by meaning rather than keyword.

---

## Main Contributions

- **9.2M extracted theorems** unified from arXiv and additional sources  
- Theorem-level evaluation benchmark  
- Embedding analysis across models and context formats  
- Demonstrated improvement over document-level search baselines  

---

## System Overview

<p align="center">
  <img src="https://github.com/user-attachments/assets/e9dd0a54-432e-4083-ba45-38a18885bd4d"
       width="85%" />
</p>

---

## Retrieval Performance

<p align="center">
  <img src="https://github.com/user-attachments/assets/089438a8-f679-4ef1-84da-bfade8d60072"
       width="85%" />
</p>

---

## Links

- **Paper (arXiv):** https://arxiv.org/abs/2602.05216  
- **Hugging Face paper page:** https://huggingface.co/papers/2602.05216  

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
