"""Bidirectional agreement analysis.

For each gold pair (informal i, formal f):
  - f2i_correct = top-1 of f's f→i row equals i  (or one of i's gold siblings)
  - i2f_correct = top-1 of i's i→f row equals f  (or one of f's gold siblings)

Bucket each pair into:
  both_correct, f2i_only, i2f_only, neither

Output: bucket counts + sample pairs from each bucket for downstream digs.
Per the literature scan (Artetxe & Schwenk 2019), forward/backward agreement
is well-established in bitext mining but has not been imported into NL↔FL
theorem matching. This module produces the numbers that anchor that claim.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "rds"))

from utils.connect import get_rds_connection  # noqa: E402
from experiments.nl_fl_matching import gold  # noqa: E402
from experiments.nl_fl_matching.analysis.eval import fetch_rows  # noqa: E402


def _top1(ranked: List[tuple]) -> str | None:
    """ranked is the list-of-(rank, cid, sim) from eval.fetch_rows."""
    for rank, cid, _sim in ranked:
        if rank == 1:
            return cid
    return None


@dataclass
class Bucketed:
    both_correct:  List[Tuple[str, str]]
    f2i_only:      List[Tuple[str, str]]
    i2f_only:      List[Tuple[str, str]]
    neither:       List[Tuple[str, str]]

    def counts(self) -> Counter:
        return Counter({
            "both_correct": len(self.both_correct),
            "f2i_only":     len(self.f2i_only),
            "i2f_only":     len(self.i2f_only),
            "neither":      len(self.neither),
        })

    @property
    def total(self) -> int:
        return sum(self.counts().values())


def bucket_pairs(
    pairs: Set[Tuple[str, str]],
    f2i_ranks: Dict[str, List[tuple]],
    i2f_ranks: Dict[str, List[tuple]],
    formal_to_gold_inf: Dict[str, Set[str]],
    informal_to_gold_fml: Dict[str, Set[str]],
) -> Bucketed:
    b = Bucketed([], [], [], [])
    for inf_sid, fml_sid in pairs:
        f2i_top = _top1(f2i_ranks.get(fml_sid, []))
        i2f_top = _top1(i2f_ranks.get(inf_sid, []))

        f2i_ok = f2i_top is not None and f2i_top in formal_to_gold_inf.get(fml_sid, set())
        i2f_ok = i2f_top is not None and i2f_top in informal_to_gold_fml.get(inf_sid, set())

        if f2i_ok and i2f_ok:
            b.both_correct.append((inf_sid, fml_sid))
        elif f2i_ok:
            b.f2i_only.append((inf_sid, fml_sid))
        elif i2f_ok:
            b.i2f_only.append((inf_sid, fml_sid))
        else:
            b.neither.append((inf_sid, fml_sid))
    return b


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--embedding-model", default="qwen3-8b")
    p.add_argument("--exclusion", default="statement")
    p.add_argument("--f2i-pool", default="gold_subset_f2i")
    p.add_argument("--i2f-pool", default="gold_subset_i2f")
    p.add_argument("--samples", type=int, default=5,
                   help="Sample pairs from each bucket to display.")
    args = p.parse_args()

    conn = get_rds_connection("v2")
    g = gold.load_gold(conn, embedding_model=args.embedding_model)
    f2i = fetch_rows(conn, "f2i", args.embedding_model,
                     pool_descriptor=args.f2i_pool, exclusion=args.exclusion)
    i2f = fetch_rows(conn, "i2f", args.embedding_model,
                     pool_descriptor=args.i2f_pool, exclusion=args.exclusion)
    conn.close()

    b = bucket_pairs(
        g.pairs, f2i, i2f,
        g.formal_to_gold_informals, g.informal_to_gold_formals,
    )

    n = b.total
    print()
    print("=" * 72)
    print(f"BIDIRECTIONAL AGREEMENT  ({n} gold pairs)")
    print("=" * 72)
    print()
    print(f"  {'bucket':<14} {'count':>8} {'pct':>7}")
    print(f"  {'-'*14} {'-'*8} {'-'*7}")
    for name, count in b.counts().most_common():
        print(f"  {name:<14} {count:>8,} {count/n:>7.1%}")
    print()

    if args.samples:
        for name, pairs in (
            ("both_correct", b.both_correct),
            ("f2i_only",     b.f2i_only),
            ("i2f_only",     b.i2f_only),
            ("neither",      b.neither),
        ):
            print(f"  -- {name} sample ({min(args.samples, len(pairs))}) --")
            for inf_sid, fml_sid in pairs[: args.samples]:
                print(f"    inf {inf_sid[:8]}  ↔  fml {fml_sid[:8]}")
            print()


if __name__ == "__main__":
    main()
