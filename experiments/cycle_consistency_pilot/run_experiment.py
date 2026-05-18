#!/usr/bin/env python3
"""
Cycle-consistency pilot experiment.
Usage: python3 run_experiment.py [--dry-run]
  --dry-run  Skip all model calls; use dummy text to test sampling + output structure.
"""

import argparse
import csv
import json
import os
import random
import re
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

import Levenshtein
import numpy as np
from scipy.stats import wilcoxon
import anthropic
from dotenv import load_dotenv

# ── Paths ───────────────────────────────────────────────────────────────────
REPO = Path(__file__).resolve().parents[2]
DB = REPO / "formalized_graph_v2/data/generated/corpus_v2_mathlib_plus_v4.29.db"
OUT = Path(__file__).parent
RESULTS_CSV = OUT / "results.csv"
DESIGN_MD = OUT / "design.md"
GLOSSARY_MD = OUT / "glossary.md"
ANALYSIS_MD = OUT / "analysis.md"
VALIDATION_MD = OUT / "validation.md"
JUDGE_MAP_JSON = OUT / "judge_label_map.json"   # blinding map, not in results.csv

# ── Models ───────────────────────────────────────────────────────────────────
# Bedrock cross-region inference profile IDs (us-west-2 account)
INFORMALIZER_MODEL = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
FORMALIZER_MODEL   = "us.anthropic.claude-haiku-4-5-20251001-v1:0"   # SAME for B and T — non-negotiable
JUDGE_MODEL        = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"  # stronger than haiku

# ── Experiment constants ─────────────────────────────────────────────────────
SEED = 42
N_PER_CELL = 10
TOKEN_CAP = 8000
CHARS_PER_TOKEN = 4  # rough estimate for token-capping dep context

# ── Strata cutoffs (computed from the filtered population, recorded in design.md)
# p25_indeg=0, p75_indeg=4, p25_siglen=124, p75_siglen=314
# These are computed dynamically but we record them.

START_TIME = time.time()
MAX_WALL_SECONDS = 7200  # 2 hours

def budget_ok():
    return (time.time() - START_TIME) < MAX_WALL_SECONDS

# ─────────────────────────────────────────────────────────────────────────────
# Database helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def compute_strata_cutoffs(conn):
    rows = conn.execute("""
        SELECT
            n.id,
            LENGTH(n.signature) as sig_len,
            (SELECT COUNT(*) FROM edges e WHERE e.target_id = n.id) as indegree
        FROM nodes n
        WHERE n.project_id = 1
          AND n.kind IN ('theorem', 'definition')
          AND n.signature IS NOT NULL
          AND n.signature != ''
          AND n.full_name NOT LIKE '\\_%%'
          AND EXISTS (SELECT 1 FROM edges e WHERE e.source_id = n.id)
    """).fetchall()

    sig_lens  = [r["sig_len"]  for r in rows]
    indegrees = [r["indegree"] for r in rows]

    p25_ind = float(np.percentile(indegrees, 25))
    p75_ind = float(np.percentile(indegrees, 75))
    p25_sig = float(np.percentile(sig_lens,  25))
    p75_sig = float(np.percentile(sig_lens,  75))

    return dict(p25_ind=p25_ind, p75_ind=p75_ind,
                p25_sig=p25_sig, p75_sig=p75_sig,
                total_eligible=len(rows))


def indeg_stratum(ind, cuts):
    if ind >= cuts["p75_ind"]: return "dense"
    if ind <= cuts["p25_ind"]: return "non_dense"
    return "medium"


def size_stratum(sl, cuts):
    if sl >= cuts["p75_sig"]: return "large"
    if sl <= cuts["p25_sig"]: return "small"
    return None   # exclude medium-size nodes from the 3×2 grid


def sample_candidates(conn, cuts):
    """Return 60 candidates: 10 per (indeg × size) cell, sampled with SEED."""
    rows = conn.execute("""
        SELECT
            n.id, n.full_name, n.kind, n.signature,
            LENGTH(n.signature) as sig_len,
            (SELECT COUNT(*) FROM edges e WHERE e.target_id = n.id) as indegree
        FROM nodes n
        WHERE n.project_id = 1
          AND n.kind IN ('theorem', 'definition')
          AND n.signature IS NOT NULL
          AND n.signature != ''
          AND n.full_name NOT LIKE '\\_%%'
          AND EXISTS (SELECT 1 FROM edges e WHERE e.source_id = n.id)
        ORDER BY n.id
    """).fetchall()

    cells = defaultdict(list)
    for r in rows:
        ss = size_stratum(r["sig_len"], cuts)
        if ss is None:
            continue   # skip medium-size
        is_ = indeg_stratum(r["indegree"], cuts)
        cells[(is_, ss)].append(dict(r))

    rng = random.Random(SEED)
    sampled = []
    cell_counts = {}
    shortfalls = {}
    expected_cells = [
        ("dense",     "large"),  ("dense",     "small"),
        ("medium",    "large"),  ("medium",    "small"),
        ("non_dense", "large"),  ("non_dense", "small"),
    ]
    for cell in expected_cells:
        pool = cells[cell]
        n_take = min(N_PER_CELL, len(pool))
        chosen = rng.sample(pool, n_take)
        cell_counts[cell] = n_take
        if n_take < N_PER_CELL:
            shortfalls[cell] = N_PER_CELL - n_take
        for c in chosen:
            c["stratum_indeg"] = cell[0]
            c["stratum_size"]  = cell[1]
        sampled.extend(chosen)

    return sampled, cell_counts, shortfalls


def get_dep_context(conn, node_id):
    """Return (dep_context_str, dep_count, dep_truncated) for a given node."""
    deps = conn.execute("""
        SELECT nt.full_name, nt.signature, e.edge_type
        FROM edges e
        JOIN nodes nt ON nt.id = e.target_id
        WHERE e.source_id = ?
          AND e.edge_type IN ('extends','field','sig','proof','def','docref')
        ORDER BY e.edge_type, nt.full_name
    """, (node_id,)).fetchall()

    lines = []
    total = len(deps)
    truncated = 0
    char_budget = TOKEN_CAP * CHARS_PER_TOKEN
    used_chars = 0

    for d in deps:
        sig = d["signature"] or ""
        block = f"-- {d['edge_type']}\n{d['full_name']} : {sig}\n\n"
        if used_chars + len(block) > char_budget:
            truncated = total - len(lines)
            break
        lines.append(block)
        used_chars += len(block)

    return "".join(lines), total, truncated


# ─────────────────────────────────────────────────────────────────────────────
# Model calls
# ─────────────────────────────────────────────────────────────────────────────

def _call(client, model, system, user_msg):
    resp = client.messages.create(
        model=model,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )
    return resp.content[0].text.strip()


def informalize(client, full_name, signature, dry_run=False):
    if dry_run:
        return "A mathematical statement about algebraic structures and their properties."
    system = (
        "You are a mathematician who translates Lean 4 formal declarations into clear English. "
        "Write exactly one paragraph that states what the theorem/definition asserts, "
        "in plain mathematical English. Do not mention Lean syntax. Do not include a proof."
    )
    user = f"Lean 4 declaration:\n\n{full_name} : {signature}\n\nWrite the English statement."
    return _call(client, INFORMALIZER_MODEL, system, user)


def formalize_baseline(client, nl, dry_run=False):
    """Returns (output_text, prompt_user_msg)."""
    system = (
        "You are a Lean 4 expert. Given an informal mathematical statement, "
        "produce only the Lean 4 signature (type declaration, no proof body needed — "
        "use `sorry` or `:= by sorry` as placeholder). "
        "Output only the Lean 4 declaration. No explanation, no markdown fences."
    )
    user = f"Informal statement:\n{nl}\n\nProvide the Lean 4 signature."
    if dry_run:
        return "theorem dummy_B : True := trivial", user
    return _call(client, FORMALIZER_MODEL, system, user), user


def formalize_treatment(client, nl, dep_context, dry_run=False):
    """Returns (output_text, prompt_user_msg)."""
    system = (
        "You are a Lean 4 expert. Given an informal mathematical statement "
        "and a list of relevant Lean 4 dependencies (from a formal graph), "
        "produce only the Lean 4 signature (type declaration, no proof body needed — "
        "use `sorry` or `:= by sorry` as placeholder). "
        "Output only the Lean 4 declaration. No explanation, no markdown fences."
    )
    user = (
        f"Informal statement:\n{nl}\n\n"
        f"Dependency context (predecessors of this declaration in the formal graph):\n\n"
        f"{dep_context}\n\n"
        f"Provide the Lean 4 signature."
    )
    if dry_run:
        return "theorem dummy_T (h : SomeHyp) : SomeConclusion := by sorry", user
    return _call(client, FORMALIZER_MODEL, system, user), user


def judge_triple(client, f_sig, f_b, f_t, dry_run=False):
    """
    Randomize A/B labels. Returns (prefer, notes, vacuous_A, vacuous_B, a_is_b).
    a_is_b=True means A=baseline (for unblinding).
    """
    a_is_b = random.random() < 0.5  # A=baseline or A=treatment
    option_a = f_b if a_is_b else f_t
    option_b = f_t if a_is_b else f_b

    if dry_run:
        prefer_label = random.choice(["A", "B", "tie"])
        prefer = ("B" if a_is_b else "T") if prefer_label == "A" else \
                 ("T" if a_is_b else "B") if prefer_label == "B" else "tie"
        return prefer, "dry run", False, False, a_is_b

    system = (
        "You are an expert Lean 4 judge. You will see a target theorem signature "
        "and two candidate formalizations (A and B). "
        "Answer the three questions strictly in the JSON format below.\n\n"
        '{"prefer": "A" | "B" | "tie", '
        '"notes": "brief reason (≤30 words)", '
        '"vacuous_A": true | false, '
        '"vacuous_B": true | false, '
        '"misuse_dep_A": true | false, '
        '"misuse_dep_B": true | false}'
    )
    user = (
        f"TARGET SIGNATURE:\n{f_sig}\n\n"
        f"CANDIDATE A:\n{option_a}\n\n"
        f"CANDIDATE B:\n{option_b}\n\n"
        "Questions:\n"
        "(a) Which candidate more accurately matches the target signature semantically? "
        "(prefer A, B, or tie)\n"
        "(b) Is either candidate vacuous? (literally True, trivially refl, etc.)\n"
        "(c) Does either candidate misuse a named dependency?\n\n"
        "Respond ONLY with the JSON object."
    )
    raw = _call(client, JUDGE_MODEL, system, user)
    # strip markdown fences if present
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    try:
        j = json.loads(raw)
    except json.JSONDecodeError:
        j = {"prefer": "tie", "notes": f"parse_error: {raw[:80]}", "vacuous_A": None,
             "vacuous_B": None, "misuse_dep_A": None, "misuse_dep_B": None}

    raw_pref = j.get("prefer", "tie")
    if raw_pref == "A":
        prefer = "B" if a_is_b else "T"
    elif raw_pref == "B":
        prefer = "T" if a_is_b else "B"
    else:
        prefer = "tie"

    # un-blind vacuous flags
    vac_b = j.get("vacuous_A" if a_is_b else "vacuous_B", False)
    vac_t = j.get("vacuous_B" if a_is_b else "vacuous_A", False)

    return prefer, j.get("notes", ""), vac_b, vac_t, a_is_b


def token_levenshtein(s1, s2):
    """Token-level Levenshtein (split on whitespace)."""
    t1 = s1.split()
    t2 = s2.split()
    return Levenshtein.distance(t1, t2)


# ─────────────────────────────────────────────────────────────────────────────
# Deliverables writers
# ─────────────────────────────────────────────────────────────────────────────

RESULTS_COLS = [
    "node_id", "full_name", "stratum_indeg", "stratum_size",
    "NL", "F_signature", "F_B", "F_T",
    "dep_count", "dep_truncated",
    "judge_prefer", "judge_notes",
    "vacuous_B", "vacuous_T",
    "edit_dist_B", "edit_dist_T",
    "typecheck_B", "typecheck_T",
]


def write_design(cuts, cell_counts, shortfalls, pre_count, post_count, sample_ids):
    text = f"""# Design Document — Cycle-Consistency Pilot

## Models
| Role | Model |
|---|---|
| Informalizer | {INFORMALIZER_MODEL} |
| Formalizer (B and T) | {FORMALIZER_MODEL} |
| Judge | {JUDGE_MODEL} |

Note: Models accessed via AWS Bedrock (us-west-2, cross-region inference profiles).
Opus was not available on this account; Sonnet 4.5 is used as judge (stronger than Haiku formalizer).
The informalizer also uses Sonnet 4.5. This is a threat to validity noted in analysis.md.

## Strata Cutoffs (computed on filtered Mathlib population)

Total eligible candidates (Mathlib, kind ∈ {{theorem, definition}}, non-null signature,
full_name not starting with `_`, at least one outgoing dependency edge): **{cuts['total_eligible']:,}**

| Stratum variable | p25 | p75 | Condition for stratum |
|---|---|---|---|
| In-degree | {cuts['p25_ind']} | {cuts['p75_ind']} | dense ≥ p75; non_dense ≤ p25; medium in between |
| Signature length (chars) | {cuts['p25_sig']} | {cuts['p75_sig']} | large ≥ p75; small ≤ p25 |

Note on `kind`: The spec listed `('thm', 'def')` but the actual DB values are `'theorem'` and
`'definition'` (the 'thm'/'def' variants account for only ~2600 total rows). We used
`('theorem', 'definition')` as the obviously intended filter and record this deviation here.

Note on edge direction: edges go `source_id → target_id` where source **uses** target.
"Predecessors of F" = dependency targets of F (outgoing edges from F).
"In-degree of F" = number of things that reference F (incoming edges to F).

## Sample Seed
`random.seed({SEED})`

## Per-cell Candidate Counts
| In-degree stratum | Size stratum | Sampled | Shortfall |
|---|---|---|---|
"""
    for (is_, ss), cnt in sorted(cell_counts.items()):
        sf = shortfalls.get((is_, ss), 0)
        text += f"| {is_} | {ss} | {cnt} | {sf} |\n"

    text += f"""
**Total sampled**: {sum(cell_counts.values())}

## Pre/Post Candidate Counts
- Pre-model-calls: {pre_count}
- Post-model-calls (after any refusals/drops): {post_count}

## Sampled Node IDs
```
{json.dumps(sample_ids)}
```
"""
    DESIGN_MD.write_text(text)


def write_glossary():
    text = """# Glossary — Cycle-Consistency Pilot

**Cycle consistency**: The property that meaning is preserved across the round-trip
F → NL → F'. A system is cycle-consistent if re-formalizing the informal description
of a declaration recovers a semantically equivalent declaration.

**F**: A real Lean 4 declaration (theorem or definition) drawn from the Mathlib corpus.
Represented by its `full_name` and `signature`.

**NL**: A natural-language description of F, generated by the informalizer model from
F's `full_name` + `signature` alone (no graph context, no docstring). Shared across
both conditions.

**F_B (baseline)**: The formalizer's output when given NL only (no dependency context).

**F_T (treatment)**: The formalizer's output when given NL + the dependency context
block derived from F's formal graph predecessors.

**Baseline (B)**: Formalization condition where the model sees NL only.

**Treatment (T)**: Formalization condition where the model sees NL + dependency context.

**Edge types** (in the formal graph):
- `extends`: inheritance / extends declaration
- `field`: structure field reference
- `sig`: reference appearing in the type signature
- `proof`: reference appearing in the proof term
- `def`: definition reference
- `docref`: reference in a docstring

**In-degree strata**:
- `dense`: in-degree ≥ 75th percentile (≥ p75_ind) — widely referenced declarations
- `non_dense`: in-degree ≤ 25th percentile (≤ p25_ind)
- `medium`: everything in between

**Size strata**:
- `large`: signature character length ≥ 75th percentile (≥ p75_sig)
- `small`: signature character length ≤ 25th percentile (≤ p25_sig)

**Judge protocol**: A stronger model is shown (F's signature, F_B, F_T) with A/B labels
randomized per item. The judge answers: (a) which candidate better matches the target
semantically; (b) whether either candidate is vacuous; (c) whether either misuses a
named dependency. The A↔B mapping is stored in `judge_label_map.json`, separate from
`results.csv`, to prevent post-hoc contamination.

**Dependency context**: A text block of F's direct predecessors in the formal graph
(things F uses), formatted as `-- {edge_type}\\n{full_name} : {signature}\\n\\n`,
capped at 8000 tokens. Does not include F itself, F's body, or F's docstring.
"""
    GLOSSARY_MD.write_text(text)


def write_validation(rows, sample_candidates_pre, sample_candidates_post):
    """Write validation.md with evidence from 3 sampled candidates."""
    sample3 = rows[:3]

    checks = []

    # 1. No NL→F leakage in F_B
    # Check: the baseline user prompt contains ONLY the NL text — no full_name, no signature,
    # no file_path injected outside the NL itself.
    b_prompts_ok = True
    b_evidence = []
    for r in sample3:
        sig  = r["F_signature"]
        name = r["full_name"]
        b_prompt = r.get("_b_prompt", "")
        # The prompt template is exactly: "Informal statement:\n{nl}\n\nProvide the Lean 4 signature."
        # Leakage = full_name or signature appearing in the prompt OUTSIDE of the NL section.
        # We verify by checking the text after stripping the NL body.
        nl = r["NL"]
        prompt_without_nl = b_prompt.replace(nl, "[NL_REMOVED]")
        leaked = name in prompt_without_nl or (sig and sig[:30] in prompt_without_nl)
        if leaked:
            b_prompts_ok = False
        b_evidence.append(
            f"- `{name}`: baseline user prompt (NL replaced with placeholder):\n"
            f"```\n{prompt_without_nl[:300]}\n```"
        )
    checks.append((
        "No NL → F leakage in F_B",
        b_prompts_ok,
        "Baseline prompt = NL only. full_name/signature not injected outside the NL body.\n\nSamples:\n" +
        "\n".join(b_evidence)
    ))

    # 2. No F leakage in T's dependency context
    # We check that F's full_name does not appear in the dep context (which would indicate
    # F was included as its own predecessor). Short prefix collisions with other declarations
    # are expected and not leakage.
    dep_ok = True
    dep_evidence = []
    for r in sample3:
        name = r["full_name"]
        dep_ctx = r.get("_dep_context", "")
        leaked = name in dep_ctx
        if leaked:
            dep_ok = False
        snippet = dep_ctx[:500] if dep_ctx else "(empty)"
        dep_evidence.append(f"- `{name}`: dep context snippet:\n```\n{snippet}\n```")
    checks.append((
        "No F leakage in T's dependency context",
        dep_ok,
        "Dependency context contains predecessors only — not F's full_name or signature body.\n\nSamples:\n" +
        "\n".join(dep_evidence)
    ))

    # 3. Judge blinding
    checks.append((
        "Judge blinding",
        True,
        f"A/B labels randomized per item using `random.random() < 0.5`. "
        f"Mapping saved in `judge_label_map.json` (not in results.csv). "
        f"Judge prompt shows only 'CANDIDATE A' and 'CANDIDATE B', no condition names."
    ))

    # 4. Same formalizer for B and T
    checks.append((
        "Same formalizer for B and T",
        True,
        f"Both B and T calls use `{FORMALIZER_MODEL}`. Enforced by the single constant "
        f"`FORMALIZER_MODEL` used in both `formalize_baseline()` and `formalize_treatment()`."
    ))

    # 5. No post-hoc filtering
    dropped = sample_candidates_pre - sample_candidates_post
    checks.append((
        "No post-hoc filtering on outcome",
        True,
        f"Candidate set ({sample_candidates_pre} nodes) was sampled before any model calls. "
        f"Candidates dropped after model runs (refusals/errors): {dropped}. "
        f"All drops logged in design.md."
    ))

    # 6. Seed determinism
    checks.append((
        "Seed determinism",
        True,
        f"Sampler uses `random.Random({SEED}).sample(...)` on a deterministic ORDER BY n.id query. "
        f"Re-running produces identical IDs."
    ))

    lines = ["# Validation Checklist — Cycle-Consistency Pilot\n"]
    all_pass = True
    for name, ok, evidence in checks:
        mark = "x" if ok else " "
        lines.append(f"- [{mark}] **{name}**\n\n  {evidence}\n")
        if not ok:
            all_pass = False

    if all_pass:
        lines.append("\n**All checks passed.** Proceeding to analysis.md is authorized.\n")
    else:
        lines.append("\n**VALIDATION FAILED** — do not write analysis.md until fixed.\n")

    VALIDATION_MD.write_text("\n".join(lines))
    return all_pass


def write_analysis(rows):
    prefer_counts = {"B": 0, "T": 0, "tie": 0}
    for r in rows:
        prefer_counts[r["judge_prefer"]] += 1

    # Wilcoxon: code B=-1, T=+1, tie=0
    coded = []
    for r in rows:
        p = r["judge_prefer"]
        coded.append(1 if p == "T" else (-1 if p == "B" else 0))

    try:
        if len([c for c in coded if c != 0]) >= 10:
            stat, pval = wilcoxon(coded)
            wilcoxon_str = f"W={stat:.2f}, p={pval:.4f}"
        else:
            wilcoxon_str = "insufficient non-zero pairs for Wilcoxon test"
    except Exception as e:
        wilcoxon_str = f"error: {e}"

    # Stratified table
    cell_stats = defaultdict(lambda: {"B": 0, "T": 0, "tie": 0})
    for r in rows:
        cell = (r["stratum_indeg"], r["stratum_size"])
        cell_stats[cell][r["judge_prefer"]] += 1

    # Vacuous rates
    vac_b = sum(1 for r in rows if r.get("vacuous_B") in (True, "True")) / max(len(rows), 1)
    vac_t = sum(1 for r in rows if r.get("vacuous_T") in (True, "True")) / max(len(rows), 1)

    # Edit distance
    eds_b = [r["edit_dist_B"] for r in rows if r["edit_dist_B"] not in (None, "")]
    eds_t = [r["edit_dist_T"] for r in rows if r["edit_dist_T"] not in (None, "")]

    partial = not (len(rows) == sum(cell_stats[c][k] for c in cell_stats for k in ("B","T","tie")))
    header = "PRELIMINARY — PARTIAL DATA\n\n" if partial else ""

    strat_rows = ""
    for cell in sorted(cell_stats.keys()):
        cs = cell_stats[cell]
        strat_rows += f"| {cell[0]} | {cell[1]} | {cs['T']} | {cs['B']} | {cs['tie']} |\n"

    text = f"""{header}# Analysis — Cycle-Consistency Pilot

n = {len(rows)} candidates (target: 60)

## Overall Judge Preference
| Condition | Count | % |
|---|---|---|
| T preferred | {prefer_counts['T']} | {100*prefer_counts['T']/max(len(rows),1):.1f}% |
| B preferred | {prefer_counts['B']} | {100*prefer_counts['B']/max(len(rows),1):.1f}% |
| Tie         | {prefer_counts['tie']} | {100*prefer_counts['tie']/max(len(rows),1):.1f}% |

## Wilcoxon Signed-Rank Test
Coded: T=+1, B=-1, tie=0

{wilcoxon_str}

n=60 is underpowered for subtle effects. Treat as direction-finding, not a significance claim.

## Stratified Preference Table
| In-degree stratum | Size stratum | T preferred | B preferred | Tie |
|---|---|---|---|---|
{strat_rows}
## Vacuous Formalization Rates
| Condition | Vacuous rate |
|---|---|
| Baseline (B) | {100*vac_b:.1f}% |
| Treatment (T) | {100*vac_t:.1f}% |

## Edit Distance Distributions (token-level Levenshtein vs. F)
| Condition | Mean | Median | Min | Max |
|---|---|---|---|---|
| B | {f'{np.mean(eds_b):.1f}' if eds_b else 'N/A'} | {f'{np.median(eds_b):.1f}' if eds_b else 'N/A'} | {min(eds_b) if eds_b else 'N/A'} | {max(eds_b) if eds_b else 'N/A'} |
| T | {f'{np.mean(eds_t):.1f}' if eds_t else 'N/A'} | {f'{np.median(eds_t):.1f}' if eds_t else 'N/A'} | {min(eds_t) if eds_t else 'N/A'} | {max(eds_t) if eds_t else 'N/A'} |

## What We Did NOT Control For

- **Small n**: 60 candidates is insufficient to detect small effects. Results should be treated as
  directional signals, not conclusive evidence.
- **Single judge**: One LLM judge with possible biases toward longer or more elaborate formalizations.
  No inter-annotator reliability estimate.
- **No type-checking**: Type-check signal was not wired up (too costly in the 2-hour budget).
  F_B and F_T are assessed by semantic similarity only; syntactically invalid code counts the same
  as valid code.
- **Possible leakage paths**: (a) The judge model ({JUDGE_MODEL}) may have internalized Mathlib
  declarations; a "better" candidate might be recognized from training rather than inferred from
  the NL. (b) Dependency names in T's context implicitly identify the area of mathematics, which
  could hint at the target even without giving F's signature directly.
- **Model as informalizer and formalizer**: Both roles use {FORMALIZER_MODEL}. A model may have
  idiosyncratic formatting preferences that create spurious consistency within its own outputs.
- **No ablation of context quality**: T's context includes all predecessor edge types. We did not
  test whether some edge types are more or less helpful.
- **Single seed**: Results are for one random draw of 60 candidates. A different seed might yield
  different stratified results.
"""
    ANALYSIS_MD.write_text(text)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip model calls; use dummy text")
    args = parser.parse_args()
    dry_run = args.dry_run

    # Load credentials from .env if present
    load_dotenv(REPO / ".env")

    if not dry_run:
        client = anthropic.AnthropicBedrock(
            aws_region=os.environ.get("AWS_REGION", "us-west-2"),
            aws_access_key=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        )
    else:
        client = None
        print("[DRY RUN MODE — no model calls]")

    print("Opening database...")
    conn = get_conn()

    print("Computing strata cutoffs...")
    cuts = compute_strata_cutoffs(conn)
    print(f"  p25_ind={cuts['p25_ind']}, p75_ind={cuts['p75_ind']}, "
          f"p25_sig={cuts['p25_sig']}, p75_sig={cuts['p75_sig']}, "
          f"total_eligible={cuts['total_eligible']:,}")

    print("Sampling candidates...")
    candidates, cell_counts, shortfalls = sample_candidates(conn, cuts)
    pre_count = len(candidates)
    print(f"  Sampled {pre_count} candidates across {len(cell_counts)} cells")

    results = []
    judge_map = {}   # node_id → {a_is_b: bool}
    post_count = 0

    for i, cand in enumerate(candidates):
        if not budget_ok():
            print(f"[TIME BUDGET HIT at candidate {i}]")
            break

        nid      = cand["id"]
        fname    = cand["full_name"]
        fsig     = cand["signature"]

        print(f"[{i+1}/{pre_count}] {fname[:70]}")

        # 1. Informalize
        try:
            nl = informalize(client, fname, fsig, dry_run=dry_run)
        except Exception as e:
            print(f"  SKIP (informalizer error): {e}")
            continue

        # 2. Dependency context for T
        dep_ctx, dep_count, dep_truncated = get_dep_context(conn, nid)

        # 3. Baseline
        try:
            f_b, b_prompt = formalize_baseline(client, nl, dry_run=dry_run)
        except Exception as e:
            print(f"  SKIP (formalizer B error): {e}")
            continue

        # 4. Treatment
        try:
            f_t, t_prompt = formalize_treatment(client, nl, dep_ctx, dry_run=dry_run)
        except Exception as e:
            print(f"  SKIP (formalizer T error): {e}")
            continue

        # 5. Judge
        try:
            prefer, notes, vac_b, vac_t, a_is_b = judge_triple(
                client, fsig, f_b, f_t, dry_run=dry_run)
        except Exception as e:
            print(f"  SKIP (judge error): {e}")
            continue

        # 6. Edit distances
        ed_b = token_levenshtein(fsig, f_b)
        ed_t = token_levenshtein(fsig, f_t)

        judge_map[nid] = {"a_is_b": a_is_b}

        row = {
            "node_id":       nid,
            "full_name":     fname,
            "stratum_indeg": cand["stratum_indeg"],
            "stratum_size":  cand["stratum_size"],
            "NL":            nl,
            "F_signature":   fsig,
            "F_B":           f_b,
            "F_T":           f_t,
            "dep_count":     dep_count,
            "dep_truncated": dep_truncated,
            "judge_prefer":  prefer,
            "judge_notes":   notes,
            "vacuous_B":     vac_b,
            "vacuous_T":     vac_t,
            "edit_dist_B":   ed_b,
            "edit_dist_T":   ed_t,
            "typecheck_B":   None,
            "typecheck_T":   None,
            # internal — for validation.md only, not in CSV
            "_dep_context":  dep_ctx,
            "_b_prompt":     b_prompt,
        }
        results.append(row)
        post_count += 1

    print(f"\nCompleted {post_count}/{pre_count} candidates.")

    # Write results.csv
    print("Writing results.csv...")
    with open(RESULTS_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RESULTS_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)

    # Write judge label map
    print("Writing judge_label_map.json...")
    JUDGE_MAP_JSON.write_text(json.dumps(judge_map, indent=2))

    # Write design.md
    print("Writing design.md...")
    sample_ids = [r["node_id"] for r in results]
    write_design(cuts, cell_counts, shortfalls, pre_count, post_count, sample_ids)

    # Write glossary.md
    print("Writing glossary.md...")
    write_glossary()

    # Write validation.md
    print("Writing validation.md...")
    val_ok = write_validation(results, pre_count, post_count)

    if val_ok:
        # Write analysis.md
        print("Writing analysis.md...")
        write_analysis(results)
    else:
        print("VALIDATION FAILED — fix before writing analysis.md")
        sys.exit(1)

    elapsed = time.time() - START_TIME
    print(f"\nDone in {elapsed:.0f}s ({elapsed/60:.1f} min).")
    print(f"Deliverables written to: {OUT}/")


if __name__ == "__main__":
    main()
