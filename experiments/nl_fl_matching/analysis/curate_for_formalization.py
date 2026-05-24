"""Curate match results into a small CSV ranked by formalization potential.

Two views, both saved as CSV next to the input JSONL:

  top_formalization_candidates.csv
    direction=i2f, rank=1, sorted by similarity desc.
    Each row: an informal statement (arxiv etc.) and its closest formal
    Lean decl. High-similarity rows are "this paper says X; this Lean
    decl says ~X; either it's already formalized or a near-miss worth
    investigating".

  top_validation_candidates.csv
    direction=f2i, rank=1, sorted by similarity desc.
    Each row: a Lean decl and its closest informal partner across arxiv.
    Used to spot-check whether Lean decls actually capture the
    mathematical content their paper-source intended.

Both CSVs trim the heavy raw `body` columns for readability — full bodies
remain in matches_all.jsonl.

Usage:
    python -m experiments.nl_fl_matching.analysis.curate_for_formalization
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


_LIGHT_COLS = [
    "rank", "similarity", "direction", "is_blueprint_gold",
    "q_sid", "q_formality", "q_kind", "q_source",
    "q_paper_title", "q_paper_external_id", "q_paper_url",
    "q_decl_name", "q_ref", "q_lean_annotation",
    "q_slogan",
    "c_sid", "c_formality", "c_kind", "c_source",
    "c_paper_title", "c_paper_external_id", "c_paper_url",
    "c_decl_name", "c_ref", "c_lean_annotation",
    "c_slogan",
]


def _trim(s, n: int = 350) -> str:
    if not isinstance(s, str):
        return s
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--in-path", type=Path,
                   default=REPO_ROOT / "experiments/nl_fl_matching/data/matches_all.jsonl")
    p.add_argument("--out-dir", type=Path,
                   default=REPO_ROOT / "experiments/nl_fl_matching/data")
    p.add_argument("--top-n", type=int, default=500,
                   help="Keep top N rows per CSV after sort.")
    args = p.parse_args()

    rows_f2i = []
    rows_i2f = []
    with args.in_path.open() as fh:
        for line in fh:
            rec = json.loads(line)
            if rec["rank"] != 1:
                continue
            rec = {k: _trim(rec.get(k)) for k in _LIGHT_COLS}
            (rows_f2i if rec["direction"] == "f2i" else rows_i2f).append(rec)

    rows_f2i.sort(key=lambda r: -r["similarity"])
    rows_i2f.sort(key=lambda r: -r["similarity"])

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in (
        ("top_validation_candidates.csv",  rows_f2i),
        ("top_formalization_candidates.csv", rows_i2f),
    ):
        path = args.out_dir / name
        keep = rows[: args.top_n] if args.top_n else rows
        with path.open("w") as fh:
            writer = csv.DictWriter(fh, fieldnames=_LIGHT_COLS,
                                    quoting=csv.QUOTE_ALL)
            writer.writeheader()
            for rec in keep:
                writer.writerow(rec)
        print(f"wrote {len(keep)} rows to {path}")

    # Also write a tiny "checked-in sample" — 5 highest-sim i2f rank-1
    # non-gold matches, easy to eyeball.
    sample_rows = [r for r in rows_i2f if not r["is_blueprint_gold"]][:5]
    sample_path = args.out_dir / "sample_formalization_candidates.csv"
    with sample_path.open("w") as fh:
        writer = csv.DictWriter(fh, fieldnames=_LIGHT_COLS,
                                quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for rec in sample_rows:
            writer.writerow(rec)
    print(f"wrote {len(sample_rows)} sample rows to {sample_path}")


if __name__ == "__main__":
    main()
