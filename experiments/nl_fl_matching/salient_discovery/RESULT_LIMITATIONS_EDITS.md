# Result & Limitations — suggested edits

**bold** = added · ~~strikethrough~~ = removed

---

## ¶Result

We find that the methodology of creating embeddings of slogan representations of both our informal and formal corpora provide a reasonable basis (88.8% of the re-judged ≥ 0.917 prefix judged to be genuine matches) by which we can source and verify candidate pairs (informal, formal) that express the same statement. Our utilization of HNSW indexing and ordered sweep not only reduces the initial daunting figure of 4.56 trillion potential candidates to a judging and verification problem per candidate edge, but also provides the direction for future research to continue to uncover previously unfound connections between the two corpora and make the process of formalizing existing math further by creating tractable distances to each informal ~~nodes~~ **node's** nearest formalized neighbor. These links provide valuable context to both human authors and automated formalization systems (§\ref{~~sec:exp3~~ **sec:ntp-autoform**}).

---

## ¶Limitations

These results can be extended and bettered in a number of ways. Primarily, judging stands to benefit from being ~~ran~~ **run** across the entire set to produce more matches and to affirm our sampled per-bin match rates. The use of more diverse models that may offer a more balanced comparison or proven reasoning capability on math content is also an important comparison. There may be more accurate or cost-effective models that can feasibly serve as judges. Moreover, pinning similarity to be the closest candidate is an imperfect measure. Because sloganization and embedding is a lossy procedure ~~(because it creates a summary) (insert finding that body of lean code cuased judge reversals)~~ **that compresses each statement to a summary — when we recovered the omitted Lean signatures, 12.5% of those previously body-less verdicts reversed (vs. 2.9% on edges that already carried a signature), dropping that subset's match rate from 93.4% to 85.8%** — the most similar match surfaced by HNSW may obscure other candidates that could provide further pairs. In tandem with greater search depth, a more exhaustive run judging not only the most similar candidate edge but all candidate edges above a meaningful threshold might produce unintuitive matches and support/challenge our results. Lastly, a larger informal dataset would significantly broaden our results as we may discount or otherwise not match well-known nodes in the lean graph on the basis of a candidate simply not being in our dataset.

---

## The missing value (verified, klone + local)

| metric | value |
|---|---|
| body-less verdicts that reversed when signature recovered | **12.5%** |
| control (edges that already had a signature) | **2.9%** |
| that subset's match rate, before → after | **93.4% → 85.8%** |

## Label to add

`graph-paper/sections/background/related-works.tex` line 11 (it has no label):

```latex
\subsection{Neural Theorem Proving \& Autoformalization}
\label{sec:ntp-autoform}
```

## Notes
- Moved the body finding out of stacked parentheses `(...)(...)` — they read as unfinished. Terse alt: *"...lossy procedure; recovering omitted Lean signatures reversed 12.5% of body-less verdicts (vs. 2.9% control)."*
- `sec:ntp-autoform` is **related work (motivation)** → the sentence claims "systems of this kind benefit," not "we proved it." Honest. Switch to `sec:exp3` only if that experiment actually consumes these matching links (stronger, evidence-based claim).
