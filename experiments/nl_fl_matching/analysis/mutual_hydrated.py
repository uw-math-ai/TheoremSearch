"""Hydrate mutual rank-1 pairs by joining against matches_all.jsonl.

Produces a CSV with full slogans + decl_name + paper context for each mutual
pair, sorted by descending min(sim_f2i, sim_i2f).

Two outputs:
  - mutual_rank1_hydrated.csv: all 400 mutuals (including gold)
  - mutual_rank1_nongold.csv:  the ~45 non-gold mutuals (highest-confidence
                               formalization-backfill candidates)

Usage:
    python -m experiments.nl_fl_matching.analysis.mutual_hydrated
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

_LIGHT_COLS = [
    "min_sim", "sim_f2i", "sim_i2f", "is_blueprint_gold",
    "informal_sid", "informal_paper_title", "informal_paper_external_id",
    "informal_ref", "informal_lean_annotation", "informal_slogan",
    "formal_sid", "formal_decl_name", "formal_module",
    "formal_paper_title", "formal_paper_external_id", "formal_slogan",
]


def _trim(s, n=350):
    if not isinstance(s, str):
        return s
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mutual-csv", type=Path,
                   default=REPO_ROOT / "experiments/nl_fl_matching/data/mutual_rank1_pairs.csv")
    p.add_argument("--jsonl", type=Path,
                   default=REPO_ROOT / "experiments/nl_fl_matching/data/matches_all.jsonl")
    p.add_argument("--out-dir", type=Path,
                   default=REPO_ROOT / "experiments/nl_fl_matching/data")
    args = p.parse_args()

    # 1. Load mutuals into a dict keyed by (inf_sid, fml_sid).
    mutuals = {}
    with args.mutual_csv.open() as fh:
        rdr = csv.DictReader(fh)
        for r in rdr:
            key = (r["informal_sid"], r["formal_sid"])
            mutuals[key] = {
                "sim_f2i":          float(r["sim_f2i"]),
                "sim_i2f":          float(r["sim_i2f"]),
                "is_blueprint_gold": r["is_blueprint_gold"] in ("True", "true", "1"),
            }
    print(f"loaded {len(mutuals):,} mutual pairs", flush=True)

    # 2. Stream JSONL, picking up hydration whenever a rank-1 row matches.
    hydration = {}
    with args.jsonl.open() as fh:
        for line in fh:
            rec = json.loads(line)
            if rec["rank"] != 1:
                continue
            if rec["direction"] == "f2i":
                key = (rec["c_sid"], rec["q_sid"])  # (inf, fml)
                if key not in mutuals:
                    continue
                h = hydration.setdefault(key, {})
                h["formal_decl_name"]           = rec.get("q_decl_name")
                h["formal_module"]              = rec.get("q_module")
                h["formal_paper_title"]         = rec.get("q_paper_title")
                h["formal_paper_external_id"]   = rec.get("q_paper_external_id")
                h["formal_slogan"]              = rec.get("q_slogan")
                h["informal_paper_title"]       = rec.get("c_paper_title")
                h["informal_paper_external_id"] = rec.get("c_paper_external_id")
                h["informal_ref"]               = rec.get("c_ref")
                h["informal_lean_annotation"]   = rec.get("c_lean_annotation")
                h["informal_slogan"]            = rec.get("c_slogan")
            elif rec["direction"] == "i2f":
                key = (rec["q_sid"], rec["c_sid"])  # (inf, fml)
                if key not in mutuals:
                    continue
                h = hydration.setdefault(key, {})
                h.setdefault("formal_decl_name",           rec.get("c_decl_name"))
                h.setdefault("formal_module",              rec.get("c_module"))
                h.setdefault("formal_paper_title",         rec.get("c_paper_title"))
                h.setdefault("formal_paper_external_id",   rec.get("c_paper_external_id"))
                h.setdefault("formal_slogan",              rec.get("c_slogan"))
                h.setdefault("informal_paper_title",       rec.get("q_paper_title"))
                h.setdefault("informal_paper_external_id", rec.get("q_paper_external_id"))
                h.setdefault("informal_ref",               rec.get("q_ref"))
                h.setdefault("informal_lean_annotation",   rec.get("q_lean_annotation"))
                h.setdefault("informal_slogan",            rec.get("q_slogan"))

    print(f"hydrated {len(hydration):,} / {len(mutuals):,} pairs from JSONL", flush=True)

    # 3. Materialize rows and write CSVs.
    rows = []
    for (inf_sid, fml_sid), m in mutuals.items():
        h = hydration.get((inf_sid, fml_sid), {})
        row = {
            "min_sim":          min(m["sim_f2i"], m["sim_i2f"]),
            "sim_f2i":          m["sim_f2i"],
            "sim_i2f":          m["sim_i2f"],
            "is_blueprint_gold": m["is_blueprint_gold"],
            "informal_sid":     inf_sid,
            "formal_sid":       fml_sid,
            **{k: _trim(h.get(k)) for k in (
                "informal_paper_title", "informal_paper_external_id",
                "informal_ref", "informal_lean_annotation", "informal_slogan",
                "formal_decl_name", "formal_module",
                "formal_paper_title", "formal_paper_external_id", "formal_slogan",
            )},
        }
        rows.append(row)
    rows.sort(key=lambda r: -r["min_sim"])

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name, filt in (
        ("mutual_rank1_hydrated.csv", lambda r: True),
        ("mutual_rank1_nongold.csv",  lambda r: not r["is_blueprint_gold"]),
    ):
        keep = [r for r in rows if filt(r)]
        path = args.out_dir / name
        with path.open("w") as fh:
            w = csv.DictWriter(fh, fieldnames=_LIGHT_COLS, quoting=csv.QUOTE_ALL)
            w.writeheader()
            for r in keep:
                w.writerow(r)
        print(f"wrote {len(keep)} rows to {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
