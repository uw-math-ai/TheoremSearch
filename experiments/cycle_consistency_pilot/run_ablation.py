#!/usr/bin/env python3
"""
Cycle-consistency ablation: T-names and T-random conditions.

Reads results.csv (reuses NL and F_T from the pilot), adds two new
formalizer conditions, judges each against T, and writes ablation_results.csv.

Usage:
    python3 run_ablation.py [--dry-run]
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
from pathlib import Path

import Levenshtein
from dotenv import load_dotenv
import anthropic

# ── Paths ────────────────────────────────────────────────────────────────────
REPO    = Path(__file__).resolve().parents[2]
DB      = REPO / "formalized_graph_v2/data/generated/corpus_v2_mathlib_plus_v4.29.db"
OUT     = Path(__file__).parent
RESULTS = OUT / "results.csv"
ABLATION_CSV     = OUT / "ablation_results.csv"
JUDGE_MAP_JSON   = OUT / "ablation_judge_label_map.json"

# ── Models (same as pilot) ───────────────────────────────────────────────────
FORMALIZER_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
JUDGE_MODEL      = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

# ── Constants ────────────────────────────────────────────────────────────────
TOKEN_CAP        = 8000
CHARS_PER_TOKEN  = 4
START_TIME       = time.time()
MAX_WALL_SECONDS = 7200   # 2-hour budget

def budget_ok():
    return (time.time() - START_TIME) < MAX_WALL_SECONDS


# ── DB helpers ───────────────────────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def get_module(conn, node_id):
    row = conn.execute("SELECT module FROM nodes WHERE id = ?", (node_id,)).fetchone()
    return row["module"] if row else None


def get_dep_names_only_context(conn, node_id):
    """T-names: predecessor full_names only, no signatures. Same edge types and order."""
    deps = conn.execute("""
        SELECT nt.full_name, e.edge_type
        FROM edges e
        JOIN nodes nt ON nt.id = e.target_id
        WHERE e.source_id = ?
          AND e.edge_type IN ('extends','field','sig','proof','def','docref')
        ORDER BY e.edge_type, nt.full_name
    """, (node_id,)).fetchall()

    lines = []
    char_budget = TOKEN_CAP * CHARS_PER_TOKEN
    used = 0
    total = len(deps)
    for d in deps:
        block = f"-- {d['edge_type']}\n{d['full_name']}\n\n"
        if used + len(block) > char_budget:
            break
        lines.append(block)
        used += len(block)

    truncated = total - len(lines)
    return "".join(lines), total, truncated


def get_random_module_context(conn, node_id, dep_count, module):
    """
    T-random: sample dep_count nodes from the same module as F (excluding F).
    Seed: random.Random(42 + node_id) for reproducibility.
    Returns (context_str, sampled_count, truncated).
    """
    if not module:
        return "", 0, 0

    pool = conn.execute("""
        SELECT full_name, signature
        FROM nodes
        WHERE module = ? AND id != ?
          AND signature IS NOT NULL AND signature != ''
        ORDER BY id
    """, (module, node_id)).fetchall()

    if not pool:
        return "", 0, 0

    rng = random.Random(42 + node_id)
    n_take = min(dep_count, len(pool))
    chosen = rng.sample(list(pool), n_take)

    lines = []
    char_budget = TOKEN_CAP * CHARS_PER_TOKEN
    used = 0
    for d in chosen:
        sig = d["signature"] or ""
        block = f"-- random\n{d['full_name']} : {sig}\n\n"
        if used + len(block) > char_budget:
            break
        lines.append(block)
        used += len(block)

    truncated = n_take - len(lines)
    return "".join(lines), n_take, truncated


# ── Model calls ──────────────────────────────────────────────────────────────

def _call(client, model, system, user_msg):
    resp = client.messages.create(
        model=model,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )
    return resp.content[0].text.strip()


_FORMALIZER_SYSTEM = (
    "You are a Lean 4 expert. Given an informal mathematical statement, "
    "produce only the Lean 4 signature (type declaration, no proof body needed — "
    "use `sorry` or `:= by sorry` as placeholder). "
    "Output only the Lean 4 declaration. No explanation, no markdown fences."
)

_FORMALIZER_SYSTEM_WITH_DEPS = (
    "You are a Lean 4 expert. Given an informal mathematical statement "
    "and a list of relevant Lean 4 context declarations, "
    "produce only the Lean 4 signature (type declaration, no proof body needed — "
    "use `sorry` or `:= by sorry` as placeholder). "
    "Output only the Lean 4 declaration. No explanation, no markdown fences."
)


def formalize_names_only(client, nl, dep_context, dry_run=False):
    user = (
        f"Informal statement:\n{nl}\n\n"
        f"Context — names of related declarations (predecessors in the formal graph):\n\n"
        f"{dep_context}\n\n"
        f"Provide the Lean 4 signature."
    )
    if dry_run:
        return "theorem dummy_Tnames : True := trivial", user
    return _call(client, FORMALIZER_MODEL, _FORMALIZER_SYSTEM_WITH_DEPS, user), user


def formalize_random(client, nl, dep_context, dry_run=False):
    user = (
        f"Informal statement:\n{nl}\n\n"
        f"Context — other declarations from the same Lean module:\n\n"
        f"{dep_context}\n\n"
        f"Provide the Lean 4 signature."
    )
    if dry_run:
        return "theorem dummy_Trandom (h : SomeRandHyp) : SomeConclusion := by sorry", user
    return _call(client, FORMALIZER_MODEL, _FORMALIZER_SYSTEM_WITH_DEPS, user), user


def judge_pair(client, f_sig, f_a_text, f_b_text, dry_run=False):
    """
    Paired judge: given target signature and two candidates (already in A/B order),
    returns (raw_prefer 'A'|'B'|'tie', notes, vacuous_A, vacuous_B).
    Caller is responsible for randomising A/B assignment and recording the map.
    """
    if dry_run:
        return random.choice(["A", "B", "tie"]), "dry run", False, False

    system = (
        "You are an expert Lean 4 judge. You will see a target theorem signature "
        "and two candidate formalizations (A and B). "
        "Answer strictly in the JSON format below — no extra text.\n\n"
        '{"prefer": "A" | "B" | "tie", '
        '"notes": "brief reason (≤30 words)", '
        '"vacuous_A": true | false, '
        '"vacuous_B": true | false}'
    )
    user = (
        f"TARGET SIGNATURE:\n{f_sig}\n\n"
        f"CANDIDATE A:\n{f_a_text}\n\n"
        f"CANDIDATE B:\n{f_b_text}\n\n"
        "Which candidate more accurately matches the target signature semantically? "
        "Is either vacuous (literally True, trivially refl, etc.)? "
        "Respond ONLY with the JSON object."
    )
    raw = _call(client, JUDGE_MODEL, system, user)
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    try:
        j = json.loads(raw)
    except json.JSONDecodeError:
        j = {"prefer": "tie", "notes": f"parse_error: {raw[:80]}", "vacuous_A": None, "vacuous_B": None}
    return j.get("prefer", "tie"), j.get("notes", ""), j.get("vacuous_A", False), j.get("vacuous_B", False)


def run_judged_pair(client, f_sig, cand_x, cand_y, dry_run=False):
    """
    Randomly assign A/B, judge, unblind.
    Returns (prefer_x_or_y: 'X'|'Y'|'tie', notes, vac_x, vac_y, a_is_x: bool).
    """
    a_is_x = random.random() < 0.5
    opt_a = cand_x if a_is_x else cand_y
    opt_b = cand_y if a_is_x else cand_x

    raw_pref, notes, vac_a, vac_b = judge_pair(client, f_sig, opt_a, opt_b, dry_run=dry_run)

    if raw_pref == "A":
        prefer = "X" if a_is_x else "Y"
    elif raw_pref == "B":
        prefer = "Y" if a_is_x else "X"
    else:
        prefer = "tie"

    vac_x = vac_a if a_is_x else vac_b
    vac_y = vac_b if a_is_x else vac_a
    return prefer, notes, vac_x, vac_y, a_is_x


def token_levenshtein(s1, s2):
    return Levenshtein.distance(s1.split(), s2.split())


# ── CSV columns ──────────────────────────────────────────────────────────────
ABLATION_COLS = [
    # identity
    "node_id", "full_name", "stratum_indeg", "stratum_size",
    # from pilot (carried forward)
    "F_signature", "NL", "F_T",
    "dep_count", "dep_truncated",
    # T-names condition
    "F_Tnames",
    "dep_names_count", "dep_names_truncated",
    "judge_T_vs_Tnames",     # 'T' | 'Tnames' | 'tie'
    "judge_T_vs_Tnames_notes",
    "vacuous_T_in_Tnames_pair", "vacuous_Tnames",
    "edit_dist_Tnames",
    # T-random condition
    "F_Trandom",
    "rand_count", "rand_truncated",
    "judge_T_vs_Trandom",    # 'T' | 'Trandom' | 'tie'
    "judge_T_vs_Trandom_notes",
    "vacuous_T_in_Trandom_pair", "vacuous_Trandom",
    "edit_dist_Trandom",
    # type-check (filled by run_typecheck.py)
    "typecheck_T", "typecheck_Tnames", "typecheck_Trandom",
]


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    dry_run = args.dry_run

    load_dotenv(REPO / ".env")

    if not dry_run:
        client = anthropic.AnthropicBedrock(
            aws_region=os.environ.get("AWS_REGION", "us-west-2"),
            aws_access_key=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        )
    else:
        client = None
        print("[DRY RUN MODE]")

    conn = get_conn()
    pilot_rows = list(csv.DictReader(open(RESULTS)))
    print(f"Loaded {len(pilot_rows)} candidates from results.csv")

    results = []
    judge_map = {}

    for i, pr in enumerate(pilot_rows):
        if not budget_ok():
            print(f"[TIME BUDGET HIT at {i}]")
            break

        nid    = int(pr["node_id"])
        fname  = pr["full_name"]
        fsig   = pr["F_signature"]
        nl     = pr["NL"]
        f_t    = pr["F_T"]
        dep_count = int(pr["dep_count"])

        print(f"[{i+1}/{len(pilot_rows)}] {fname[:70]}")

        # T-names context
        names_ctx, names_cnt, names_trunc = get_dep_names_only_context(conn, nid)

        # T-random context
        module = get_module(conn, nid)
        rand_ctx, rand_cnt, rand_trunc = get_random_module_context(conn, nid, dep_count, module)

        # Formalize T-names
        try:
            f_tnames, _ = formalize_names_only(client, nl, names_ctx, dry_run=dry_run)
        except Exception as e:
            print(f"  SKIP T-names ({e})")
            continue

        # Formalize T-random
        try:
            f_trandom, _ = formalize_random(client, nl, rand_ctx, dry_run=dry_run)
        except Exception as e:
            print(f"  SKIP T-random ({e})")
            continue

        # Judge T vs T-names
        try:
            pref_tnames, notes_tnames, vac_t1, vac_tnames, a_is_t1 = run_judged_pair(
                client, fsig, f_t, f_tnames, dry_run=dry_run)
        except Exception as e:
            print(f"  SKIP judge T-vs-Tnames ({e})")
            continue
        # Map X=T, Y=Tnames
        prefer_tnames_label = "T" if pref_tnames == "X" else ("Tnames" if pref_tnames == "Y" else "tie")

        # Judge T vs T-random
        try:
            pref_trandom, notes_trandom, vac_t2, vac_trandom, a_is_t2 = run_judged_pair(
                client, fsig, f_t, f_trandom, dry_run=dry_run)
        except Exception as e:
            print(f"  SKIP judge T-vs-Trandom ({e})")
            continue
        prefer_trandom_label = "T" if pref_trandom == "X" else ("Trandom" if pref_trandom == "Y" else "tie")

        judge_map[nid] = {
            "T_vs_Tnames_a_is_T": a_is_t1,
            "T_vs_Trandom_a_is_T": a_is_t2,
        }

        results.append({
            "node_id":                    nid,
            "full_name":                  fname,
            "stratum_indeg":              pr["stratum_indeg"],
            "stratum_size":               pr["stratum_size"],
            "F_signature":                fsig,
            "NL":                         nl,
            "F_T":                        f_t,
            "dep_count":                  dep_count,
            "dep_truncated":              pr["dep_truncated"],
            "F_Tnames":                   f_tnames,
            "dep_names_count":            names_cnt,
            "dep_names_truncated":        names_trunc,
            "judge_T_vs_Tnames":          prefer_tnames_label,
            "judge_T_vs_Tnames_notes":    notes_tnames,
            "vacuous_T_in_Tnames_pair":   vac_t1,
            "vacuous_Tnames":             vac_tnames,
            "edit_dist_Tnames":           token_levenshtein(fsig, f_tnames),
            "F_Trandom":                  f_trandom,
            "rand_count":                 rand_cnt,
            "rand_truncated":             rand_trunc,
            "judge_T_vs_Trandom":         prefer_trandom_label,
            "judge_T_vs_Trandom_notes":   notes_trandom,
            "vacuous_T_in_Trandom_pair":  vac_t2,
            "vacuous_Trandom":            vac_trandom,
            "edit_dist_Trandom":          token_levenshtein(fsig, f_trandom),
            "typecheck_T":                "",
            "typecheck_Tnames":           "",
            "typecheck_Trandom":          "",
        })

    print(f"\nCompleted {len(results)}/{len(pilot_rows)} candidates.")

    with open(ABLATION_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ABLATION_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)
    print(f"Wrote {ABLATION_CSV}")

    JUDGE_MAP_JSON.write_text(json.dumps(judge_map, indent=2))
    print(f"Wrote {JUDGE_MAP_JSON}")

    elapsed = time.time() - START_TIME
    print(f"Done in {elapsed:.0f}s ({elapsed/60:.1f} min).")


if __name__ == "__main__":
    main()
