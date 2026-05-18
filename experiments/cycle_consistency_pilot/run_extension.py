#!/usr/bin/env python3
"""
Cycle-consistency generalization test: run B vs T pilot on a non-Mathlib project.

Reuses the formalizer/judge/dep-context logic from run_experiment.py but
samples uniformly (no stratification — non-Mathlib projects are too skewed).

Usage:
    python3 run_extension.py --project combinatorial-games [--n 60] [--dry-run]
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
import numpy as np
from dotenv import load_dotenv
import anthropic

# Import the model-call helpers from run_experiment so behaviour is identical
sys.path.insert(0, str(Path(__file__).parent))
from run_experiment import (
    informalize, formalize_baseline, formalize_treatment, judge_triple,
    token_levenshtein, strip_fences, get_dep_context,
    INFORMALIZER_MODEL, FORMALIZER_MODEL, JUDGE_MODEL, TOKEN_CAP, CHARS_PER_TOKEN,
)

REPO = Path(__file__).resolve().parents[2]
DB   = REPO / "formalized_graph_v2/data/generated/corpus_v2_mathlib_plus_v4.29.db"
OUT  = Path(__file__).parent
SEED = 42


def get_conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def sample_uniform(conn, project_name, n):
    proj = conn.execute("SELECT id FROM projects WHERE name = ?", (project_name,)).fetchone()
    if not proj:
        raise SystemExit(f"Project not found: {project_name}")
    rows = conn.execute("""
        SELECT n.id, n.full_name, n.kind, n.signature, n.module,
          (SELECT COUNT(*) FROM edges e WHERE e.target_id = n.id) as indeg
        FROM nodes n
        WHERE n.project_id = ?
          AND n.kind IN ('theorem', 'definition')
          AND n.signature IS NOT NULL AND n.signature != ''
          AND n.full_name NOT LIKE '\\_%%'
          AND EXISTS (SELECT 1 FROM edges e WHERE e.source_id = n.id)
        ORDER BY n.id
    """, (proj["id"],)).fetchall()
    print(f"  {project_name}: {len(rows)} eligible")
    rng = random.Random(SEED)
    n = min(n, len(rows))
    return [dict(r) for r in rng.sample(list(rows), n)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--n", type=int, default=60)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(REPO / ".env")
    if args.dry_run:
        client = None
        print("[DRY RUN]")
    else:
        client = anthropic.AnthropicBedrock(
            aws_region=os.environ.get("AWS_REGION", "us-west-2"),
            aws_access_key=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        )

    conn = get_conn()
    print(f"Sampling {args.n} candidates from {args.project}...")
    candidates = sample_uniform(conn, args.project, args.n)
    print(f"  Sampled {len(candidates)}")

    results = []
    judge_map = {}
    t0 = time.time()

    for i, cand in enumerate(candidates):
        nid = cand["id"]
        fname = cand["full_name"]
        fsig = cand["signature"]
        print(f"[{i+1}/{len(candidates)}] {fname[:70]}")

        try:
            nl = informalize(client, fname, fsig, dry_run=args.dry_run)
        except Exception as e:
            print(f"  SKIP informalize: {e}"); continue

        dep_ctx, dep_count, dep_trunc = get_dep_context(conn, nid)

        try:
            f_b, _ = formalize_baseline(client, nl, dry_run=args.dry_run)
        except Exception as e:
            print(f"  SKIP B: {e}"); continue

        try:
            f_t, _ = formalize_treatment(client, nl, dep_ctx, dry_run=args.dry_run)
        except Exception as e:
            print(f"  SKIP T: {e}"); continue

        try:
            prefer, notes, vac_b, vac_t, a_is_b = judge_triple(
                client, fsig, f_b, f_t, dry_run=args.dry_run)
        except Exception as e:
            print(f"  SKIP judge: {e}"); continue

        judge_map[nid] = {"a_is_b": a_is_b}
        results.append({
            "node_id":      nid,
            "full_name":    fname,
            "project":      args.project,
            "module":       cand["module"],
            "indeg":        cand["indeg"],
            "sig_len":      len(fsig),
            "NL":           nl,
            "F_signature":  fsig,
            "F_B":          f_b,
            "F_T":          f_t,
            "dep_count":    dep_count,
            "dep_truncated": dep_trunc,
            "judge_prefer": prefer,
            "judge_notes":  notes,
            "vacuous_B":    vac_b,
            "vacuous_T":    vac_t,
            "edit_dist_B":  token_levenshtein(fsig, f_b),
            "edit_dist_T":  token_levenshtein(fsig, f_t),
        })

    out_csv = OUT / f"results_{args.project}.csv"
    map_json = OUT / f"judge_label_map_{args.project}.json"
    if results:
        with open(out_csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
            w.writeheader()
            w.writerows(results)
    map_json.write_text(json.dumps(judge_map, indent=2))

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.0f}s. {len(results)}/{len(candidates)} candidates.")
    print(f"Wrote {out_csv.name}")

    from collections import Counter
    c = Counter(r["judge_prefer"] for r in results)
    print(f"Judge: T={c['T']}  B={c['B']}  tie={c['tie']}")


if __name__ == "__main__":
    main()
