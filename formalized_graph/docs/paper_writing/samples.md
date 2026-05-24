# Sample Records

Two real rows per table, chosen so that the fields a paper most likely
cites (embedding vectors, `lean` bridge annotations, decl names, etc.)
are populated. Long text fields are truncated at
~400 characters. Embedding vectors are shown as
`<dim, norm, first 6, last 6>` rather than the full 4096 floats.

## `paper`

**row 1**

| field | value |
|---|---|
| `paper_id` | 000001c6-8298-4560-b04d-0536143afbd4 |
| `kind` | paper |
| `source` | arXiv |
| `title` | Second-Order $\Gamma$-Limit for the Cahn-Hilliard Functional with Dirichlet Boundary Conditions, I |
| `authors` | ['Irene Fonseca', 'Leonard Kreutz', 'Giovanni Leoni'] |
| `url` | https://arxiv.org/pdf/2501.10452 |
| `external_id` | 2501.10452 |
| `categories` | ['math.AP'] |
| `updated_at` | 2025-08-18 00:00:00+00:00 |

**row 2**

| field | value |
|---|---|
| `paper_id` | 00000e4c-6c3a-48d1-9939-fed89c9d4f3b |
| `kind` | paper |
| `source` | arXiv |
| `title` | The time evolution equation for advective heat transport as a constraint ⏎   for optimal bounds in Rayleigh-B\'enard convection |
| `authors` | ['A. Tilgner'] |
| `url` | https://arxiv.org/pdf/1812.09156 |
| `external_id` | 1812.09156 |
| `categories` | ['physics.flu-dyn'] |
| `updated_at` | 2019-01-10 00:00:00+00:00 |

## `arxiv_paper_metadata`

**row 1**

| field | value |
|---|---|
| `arxiv_id` | 2105.05731 |
| `journal_ref` | Acta Sci. Math. (Szeged) 86 (2020), no. 3-4, 667-670 |
| `doi` | 10.14232/actasm-018-335-6 |
| `license` | http://arxiv.org/licenses/nonexclusive-distrib/1.0/ |
| `abstract` |   A result due to Williams, Stampfli and Fillmore shows that an essential ⏎ isometry $T$ on a Hilbert space $\mathcal{H}$ is a compact perturbation of an ⏎ isometry if and only if ind$(T)\le 0$. A recent result of S. Chavan yields an ⏎ analogous characterization of essential spherical isometries ⏎ $T=(T_1,\dots,T_n)\in\mathcal{B}(\mathcal{H})^n$ with ⏎ dim($\bigcap_{i=1}^n\ker(T_i))\le$ dim$(\bigcap_{i=1}^n… [+173 chars] |
| `citation_count` | 0 |
| `reference_ids` | ['DOI:10.14232/actasm-018-335-6', 'S2:d427e628491b7228ba061ffa53cd3e184e22a250'] |
| `preamble` | \documentclass[12pt,a4paper]{amsart} ⏎ \usepackage{amsfonts} ⏎ \usepackage{amsthm} ⏎ \usepackage{amsmath} ⏎ \usepackage{amscd} ⏎ \usepackage[latin2]{inputenc} ⏎ \usepackage{t1enc} ⏎ \usepackage[mathscr]{eucal} ⏎ \usepackage{indentfirst} ⏎ \usepackage{graphicx} ⏎ \usepackage{graphics} ⏎ \usepackage{pict2e} ⏎ \usepackage{epic} ⏎ \usepackage{amssymb} ⏎ \usepackage{amstext} ⏎ \usepackage{ucs} ⏎ \usepackage[plainpages=false,pdfpagela… [+678 chars] |
| `bibliography` | {"book": {"title": "J. Eschmeier and M. Putinar, Analytic sheaves and spectral decompositions, London Mathematical Monographs, New Series 10, Oxford University Press, New York(1996)."}, "FSW72": {"title": "P.A. Fillmore and J.G. Stampfli and J.P. Williams , On the essential numerical range, the essential spectrum, and a problem of Halmos, Acta Sci. Math. (Szeged) (1972), 179-192."}, "article": {"t… [+220 chars] |
| `bibtex` | false |
| `in_validation` | false |

**row 2**

| field | value |
|---|---|
| `arxiv_id` | 2105.05736 |
| `journal_ref` | NULL |
| `doi` | NULL |
| `license` | http://creativecommons.org/licenses/by/4.0/ |
| `abstract` |   Negative sampling schemes enable efficient training given a large number of ⏎ classes, by offering a means to approximate a computationally expensive loss ⏎ function that takes all labels into account. In this paper, we present a new ⏎ connection between these schemes and loss modification techniques for ⏎ countering label imbalance. We show that different negative sampling schemes ⏎ implicitly trade-off… [+333 chars] |
| `citation_count` | 12 |
| `reference_ids` | ['ARXIV:2007.07314', 'DOI:10.18653/v1/2020.acl-main.209', 'ARXIV:2003.05176', 'ARXIV:2002.06298', 'ARXIV:1911.08731', 'ARXIV:1910.09217', 'DOI:10.1145/3298689.3346996', 'ARXIV:1907.10747', 'ARXIV:1906.07413', 'ARXIV:1904.05160', 'ARXIV:1901.05555', 'DOI:10.1515/cog-2017-0109', 'ARXIV:1810.11671', 'ARXIV:1810.07076', 'ARXIV:1802.04220', 'ARXIV:1712.00527', 'DOI:10.1109/TKDE.2017.2754499', 'ARXIV:1710.05381', 'ARXIV:1709.01450', 'ARXIV:1706.07881', 'ARXIV:1706.02677', 'DOI:10.1145/2983323.2983874', 'DOI:10.1145/2959100.2959190', 'DOI:10.1145/2939672.2939756', 'ARXIV:1512.03385', 'ARXIV:1511.06481', 'S2:f4c018bcc8ea707b83247866bdc8ccb87cd9f5da', 'DOI:10.1145/2623330.2623651', 'ARXIV:1310.4546', 'DOI:10.1145/2488388.2488391', 'DOI:10.1109/ICDM.2011.33', 'DOI:10.1109/TNN.2007.912312', 'DOI:10.1109/CVPR.2006.100', 'DOI:10.5555/1005332.1044701', 'DOI:10.17877/DE290R-3088', 'S2:4f582a003bc01f6cffeb3b6efb6fbcf8a2389245', 'DOI:10.1177/0049124189017003003', 'DOI:10.4018/978-1-5225-2255-3.CH159', 'DOI:10.4230/DagRep.8.7.62', 'S2:e0021d61c2ab1334bc725852edd44597f4c65dff', 'DOI:10.5555/2503308.2188396', 'ARXIV:1106.1813', 'S2:5eb1b872bd1ded1a293935697eb7f0af37bf6635'] |
| `preamble` | \documentclass[11pt]{article} ⏎  ⏎ \usepackage{booktabs}  ⏎ \usepackage[normalem]{ulem} ⏎ \usepackage{authblk} ⏎  ⏎  ⏎ \usepackage[dvipsnames,usenames]{xcolor} ⏎  ⏎ \usepackage{url} ⏎  ⏎ \usepackage[colorlinks=true,citecolor=ForestGreen]{hyperref} ⏎  ⏎ \usepackage[left=1.25in, top=1in, bottom=1in, right=1.25in]{geometry} ⏎ \parskip 2.mm ⏎ \parindent 0.mm ⏎  ⏎ % ⏎ \title{Disentangling Sampling and Labeling Bias for Learning in Large-… [+9949 chars] |
| `bibliography` | {"V18": {"title": "Manik Varma. Extreme classification repository. Website, 8 2018. http://manikvarma.org/downloads/XC/XMLRepository.html."}, "HeGa09": {"title": "Haibo He and Edwardo~A. Garcia. Learning from imbalanced data. IEEE Transactions on Knowledge and Data Engineering, 210 (9):0 1263--1284, 2009."}, "He:2016": {"title": "K.~He, X.~Zhang, S.~Ren, and J.~Sun. Deep residual learning for imag… [+11784 chars] |
| `bibtex` | false |
| `in_validation` | false |

## `lean_community_paper_metadata`

**row 1**

| field | value |
|---|---|
| `repo_slug` | emilyriehl/infinity-cosmos |
| `branch` | main |
| `src_path` | blueprint/src |
| `preamble` | % In this file you should put the actual content of the blueprint. ⏎ % It will be used both by the web and the print version. ⏎ % It should *not* include the |
| `bibliography` | {"HoTT:2013": {"title": "Homotopy Type Theory: Univalent Foundations of Mathematics"}, "Ara:2014hq": {"title": "Higher quasi-categories vs higher {R}ezk spaces"}, "BLV:2020af": {"title": "\\normalfont Adjoint functor theorems for homotopically enriched categories"}, "Day:1970oc": {"title": "On closed categories of functors"}, "Low:2013hb": {"title": "The homotopy bicategory of $(\\infty,1)$-catego… [+14937 chars] |
| `bibtex` | true |

**row 2**

| field | value |
|---|---|
| `repo_slug` | thefundamentaltheor3m/Sphere-Packing-Lean |
| `branch` | main |
| `src_path` | blueprint/src |
| `preamble` | % This file makes a printable version of the blueprint ⏎ % It should include all the \usepackage needed for the pdf version. ⏎ % The template version assume you want to use a modern TeX compiler ⏎ % such as xeLaTeX or luaLaTeX including support for unicode ⏎ % and Latin Modern Math font with standard bugfixes applied. ⏎ % It also uses expl3 in order to support macros related to the dependency graph. ⏎ % It al… [+4159 chars] |
| `bibliography` | {"Ma": {"title": "Manin, Yu. I., Real multiplication and noncommutative geometry (ein Alterstraum). The legacy of Niels Henrik Abel, 685-727, Springer, Berlin, 2004. %"}, "BRV": {"title": "A. Bondarenko, D. Radchenko, M. Viazovska, On optimal asymptotic bounds for spherical designs, Annals of Math. 178 (2)(2013), pp. 443--452."}, "Lee": {"title": "S. Lee, Algebraic proof of modular form inequaliti… [+4838 chars] |
| `bibtex` | false |

## `lean_repo_metadata`

_(no matching sample row)_

## `statement`

**row 1**

| field | value |
|---|---|
| `statement_id` | f7577c7e-c2c1-40a4-881d-101d90a0bc33 |
| `paper_id` | 3b740cc9-1f7c-45b0-8603-bb66136cf421 |
| `formality` | informal |
| `kind` | proposition |
| `body` | Let $\mathcal I\subseteq 2^{D}$ be a family of index sets such that $\set{m_I\colon I\in\mathcal I}$ is a valid set of cross-moments. The maximum entropy distribution having the specified cross-moments has the form $\centering{\colorbox{Yellow}{\parbox{0.9\textwidth}{}}}\flushleft{}(\v \gamma)=\exp(\sum_{I\in \mathcal I}a_I\prod_{i\in I}\gamma_i)/ [\sum_{\v\gamma\in\mathbb{B}^{d}}\exp(\sum_{I\in \… [+39 chars] |
| `proof` | Define the Lagrange multipliers $L(\pi,\v a)=\sum_{I\in \mathcal I}a_{I}[\sum_{\v\gamma\in\mathbb{B}^{d}}\pi(\v\gamma)\prod_{i\in I}\gamma_i-m_I]$ and differentiate $\partial[H(\pi)+L(\pi,\v a)]/\partial \pi(\v\gamma)=-\log[\pi(\v\gamma)]-1+\sum_{I\in \mathcal I}a_{I}\prod_{i\in I}\gamma_i$. Solving the first order condition and normalizing completes the proof. |

**row 2**

| field | value |
|---|---|
| `statement_id` | c731122f-2b99-4497-ae0e-e814994a8300 |
| `paper_id` | 2f5fd1d1-8e18-435f-a048-3d00c6e50f15 |
| `formality` | formal |
| `kind` | instance |
| `body` | Lean.instInhabitedStructureInfo : Inhabited Lean.StructureInfo |
| `proof` | NULL |

## `informal_metadata`

**row 1**

| field | value |
|---|---|
| `statement_id` | d09e4d5d-42f1-4c1c-9b43-b872354e3271 |
| `ordinal` | 8 |
| `ref` | 2.1 |
| `label` | dissociated |
| `note` | Dissociation |
| `pre_context` | ] ⏎ This follows by the triangle inequality applied $k$ times if we knew that, for $1\leq l\leq k$, ⏎ \[\lvert \tau_{t_1+\cdots+t_l}F(x)-\tau_{t_1+\cdots+t_{l-1}}F(x)\rvert \leq \epsilon/k.\] ⏎ We can write the left-hand side as ⏎ \[\lvert \tau_{t_1+\cdots+t_l}F(x)-\tau_{t_1+\cdots+t_{l-1}}F(x)\rvert=\lvert \tau_{t_l}F(x-t_1-\cdots-t-{l-1})-F(x-t_1-\cdots-t-{l-1})\rvert.\] ⏎ The right-hand side is at most ⏎ \… [+98 chars] |
| `post_context` | NULL |
| `lean` | AddDissociated |

**row 2**

| field | value |
|---|---|
| `statement_id` | cd29da73-0d65-437e-ac2f-8ad9d080eea8 |
| `ordinal` | 0 |
| `ref` | 1.1 |
| `label` | mzi |
| `note` | Marcinkiewicz-Zygmund inequality |
| `pre_context` | \declaretheorem[sibling=theorem]{lemma} ⏎ \declaretheorem[sibling=theorem]{definition} ⏎ \declaretheorem[sibling=theorem]{example} ⏎  ⏎  ⏎ \newcommand{\proves}[1]{} ⏎ \newcommand{\lean}[1]{} ⏎ \newcommand{\leanok}{} ⏎  ⏎  ⏎  ⏎ \ExplSyntaxOn ⏎ \NewDocumentCommand{\uses}{m} ⏎  {\clist_map_inline:nn{#1}{\vphantom{\ref{##1}}} ⏎   \ignorespaces} ⏎ \ExplSyntaxOff ⏎  ⏎ \title{Arithmetic Progressions - Almost Periodicity} ⏎ \author{Thomas B… [+97 chars] |
| `post_context` | NULL |
| `lean` | Real.marcinkiewicz_zygmund', Real.marcinkiewicz_zygmund |

## `formal_metadata`

**row 1**

| field | value |
|---|---|
| `statement_id` | 12489b59-390a-408d-b696-bafea34a4a2d |
| `file_path` | Init/Prelude.lean |
| `decl_name` | Inhabited |
| `module` | Init.Prelude |
| `docstring` | `Inhabited α` is a typeclass that says that `α` has a designated element, ⏎ called `(default : α)`. This is sometimes referred to as a "pointed type". ⏎  ⏎ This class is used by functions that need to return a value of the type ⏎ when called "out of domain". For example, `Array.get! arr i : α` returns ⏎ a value of type `α` when `arr : Array α`, but if `i` is not in range of ⏎ the array, it reports a panic mes… [+180 chars] |
| `is_instance` | false |

**row 2**

| field | value |
|---|---|
| `statement_id` | 6dfeee02-3f8b-4bde-a50a-c7949067989a |
| `file_path` | Lean/Structure.lean |
| `decl_name` | Lean.StructureInfo |
| `module` | Lean.Structure |
| `docstring` | Data about a type created with the `structure` command. ⏎  |
| `is_instance` | false |

## `informal_dependency`

**row 1**

| field | value |
|---|---|
| `src_id` | 51cf8c08-c1ad-486c-86c6-7068274dd864 |
| `location` | pre_context |
| `cite_id` | 3361f9e6-4504-447f-a3ac-68115acf6dca |
| `cite_key` | LW1 |
| `dep_id` | 0a5fd1d5-7f13-4847-a580-34319f86847c |
| `dep_key` | LW1\|the following |
| `dep_name` | Theorem 6 |
| `methods` | ['heuristic'] |

**row 2**

| field | value |
|---|---|
| `src_id` | d43e6a0a-7efd-4214-8da1-fa6208af903d |
| `location` | post_context |
| `cite_id` | 9bea1ad0-9ae8-4cee-9cf9-c921fb2cbb5e |
| `cite_key` | lin |
| `dep_id` | 240cfcc5-e29c-47b0-b40b-fa3a8caee2e1 |
| `dep_key` | lin\|in view of |
| `dep_name` | Theorem 1.4 |
| `methods` | ['heuristic'] |

## `formal_dependency`

**row 1**

| field | value |
|---|---|
| `src_id` | c731122f-2b99-4497-ae0e-e814994a8300 |
| `dep_id` | 12489b59-390a-408d-b696-bafea34a4a2d |
| `edge_type` | sig |
| `tactic_context` | NULL |
| `position` | conclusion |
| `binder` | explicit |
| `role` | fn |
| `via_proj` | false |

**row 2**

| field | value |
|---|---|
| `src_id` | c731122f-2b99-4497-ae0e-e814994a8300 |
| `dep_id` | 6dfeee02-3f8b-4bde-a50a-c7949067989a |
| `edge_type` | sig |
| `tactic_context` | NULL |
| `position` | conclusion |
| `binder` | explicit |
| `role` | arg |
| `via_proj` | false |

## `notation`

**row 1**

| field | value |
|---|---|
| `notation_id` | 4bec4b96-de57-4bfc-a81f-54bfddb43a98 |
| `statement_id` | bbe813e1-276a-482b-8162-0c4235f0c0b4 |
| `pattern` | Q_0 |
| `description` | null forms Q_0 and Q_{\alpha, \beta} |
| `created_at` | 2026-05-11 22:40:10.162610+00:00 |

**row 2**

| field | value |
|---|---|
| `notation_id` | ba461d35-0397-414e-acf5-6ea8e4c88c94 |
| `statement_id` | bbe813e1-276a-482b-8162-0c4235f0c0b4 |
| `pattern` | Q_{\\alpha, \\beta} |
| `description` | null forms Q_{\alpha, \beta} |
| `created_at` | 2026-05-11 22:40:10.162610+00:00 |

## `slogan_prompt`

**row 1**

| field | value |
|---|---|
| `name` | formal |
| `template` | {# budget: 4000 #} ⏎ Write a 1-3 sentence, plain-English standalone summary of the following Lean mathematical declaration. ⏎ Use ASCII characters only — no LaTeX, no Unicode math. ⏎ Describe what the declaration says without referring to it as "this theorem" / "this declaration". ⏎  ⏎ {{ target_block }} ⏎  ⏎ {% if deps_text %} ⏎ Related context ({{ deps_included }}/{{ deps_available }} dependencies): ⏎ {{ deps_tex… [+17 chars] |
| `created_at` | 2026-05-19 07:04:29.434162+00:00 |

**row 2**

| field | value |
|---|---|
| `name` | minimal |
| `template` | Write a 1-4 sentence, plain-English standalone summary of the following mathematical statement. ⏎ Use words in ASCII characters only, no LaTeX or Unicode. ⏎ Describe the result without referencing it as "this statement" or similar. ⏎ If you believe this is insufficient context to summarise this statement, respond with exactly "INSUFFICIENT CONTEXT: " followed by a short reason. ⏎  ⏎ {{ statement.kind \| titl… [+84 chars] |
| `created_at` | 2026-05-13 20:12:17.245489+00:00 |

## `slogan_model`

**row 1**

| field | value |
|---|---|
| `name` | qwen3-235b |
| `model` | Qwen/Qwen3-235B-A22B-Instruct-2507 |
| `temperature` | 0.3 |
| `max_tokens` | 256 |
| `created_at` | 2026-05-11 06:13:24.948887+00:00 |

**row 2**

| field | value |
|---|---|
| `name` | pilot-claude-sonnet-4-6 |
| `model` | claude-sonnet-4-6 |
| `temperature` | NULL |
| `max_tokens` | 600 |
| `created_at` | 2026-05-13 23:20:24.799664+00:00 |

## `slogan`

**row 1**

| field | value |
|---|---|
| `slogan_id` | 01f49b12-67d2-4bc2-833f-3aa3dd0d1915 |
| `statement_id` | cd29da73-0d65-437e-ac2f-8ad9d080eea8 |
| `prompt_name` | minimal |
| `model_name` | qwen3-235b |
| `slogan` | For a function f with average value zero and absolute value at most 2, the expected value of the 2m-th power of the sum of n independent copies of f is at most (4mn) raised to the power m. |
| `in_tokens` | 208 |
| `out_tokens` | 49 |
| `created_at` | 2026-05-13 20:12:32.594649+00:00 |
| `insufficient_context` | false |

**row 2**

| field | value |
|---|---|
| `slogan_id` | 828739f1-6cae-4366-b6d9-930997d7c4d3 |
| `statement_id` | c731122f-2b99-4497-ae0e-e814994a8300 |
| `prompt_name` | formal |
| `model_name` | qwen3-235b |
| `slogan` | Lean.StructureInfo has a default value defined because it is an inhabited type, meaning a valid instance can always be returned even in cases where no specific data is available. This default value helps prevent errors in programs that require a structure info object. The type contains data about structure fields and parent types in Lean. |
| `in_tokens` | 268 |
| `out_tokens` | 63 |
| `created_at` | 2026-05-23 04:18:45.342251+00:00 |
| `insufficient_context` | false |

## `embedding_model`

**row 1**

| field | value |
|---|---|
| `name` | qwen3-8b |
| `model` | Qwen/Qwen3-Embedding-8B |
| `instruction` | Represent the given math statement for retrieving related statements by natural language query. ⏎  |
| `dim` | 4096 |
| `normalized` | true |
| `created_at` | 2026-05-15 06:34:38.106587+00:00 |

## `embedding`

**row 1**

| field | value |
|---|---|
| `embedding_id` | 71cd7c7f-223e-4f3b-9f1d-e178ff9e91a6 |
| `slogan_id` | 00060ea1-b1e0-437c-bde2-f69352baa700 |
| `model_name` | qwen3-8b |
| `embedding` | <dim=4096 norm=1.0000 head=[-0.0083, +0.0022, +0.0036, -0.0265, +0.0028, +0.0162] tail=[+0.0099, -0.0080, +0.0219, -0.0107, -0.0074, -0.0036]> |
| `created_at` | 2026-05-15 06:34:59.988999+00:00 |

**row 2**

| field | value |
|---|---|
| `embedding_id` | fdf77896-b579-483f-b7a1-dd75f58bc71b |
| `slogan_id` | 0013f294-d4d6-4f9c-9b3a-d0d6e41d5551 |
| `model_name` | qwen3-8b |
| `embedding` | <dim=4096 norm=1.0000 head=[+0.0477, +0.0025, +0.0008, -0.0203, -0.0052, +0.0107] tail=[+0.0168, -0.0190, -0.0118, +0.0028, -0.0043, +0.0054]> |
| `created_at` | 2026-05-15 06:34:59.988999+00:00 |

## `arxiv_parse_status`

**row 1**

| field | value |
|---|---|
| `arxiv_id` | 2406.00228 |
| `last_parse_attempt_at` | 2026-04-13 23:31:03.276143+00:00 |
| `error` | NULL |
| `parsing_method` | regex |
| `validation_level` | statement |

**row 2**

| field | value |
|---|---|
| `arxiv_id` | 2308.12297 |
| `last_parse_attempt_at` | 2026-04-12 05:14:43.368742+00:00 |
| `error` | [EMPTY ERROR] No statements found |
| `parsing_method` | regex |
| `validation_level` | statement |
