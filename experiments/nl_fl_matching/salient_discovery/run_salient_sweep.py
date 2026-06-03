"""Broad formal->informal sweep over the saliency-ordered manifest.

READ-ONLY against RDS (reuses topk.embedding_topk: binary-Hamming shortlist +
cosine rerank over the existing pgvector HNSW index). Writes top-K informal
matches per formal query to a per-shard JSONL on disk (gscratch on klone).
NEVER writes to RDS. Checkpoint/resume safe: re-running skips query_sids
already present in the shard's output file (survives ckpt preemption).

Sharding: the manifest is pre-sorted by saliency prior (descending), so a
contiguous shard block i = rows [i*chunk, (i+1)*chunk). With a SLURM array
capped at %W concurrency, low array indices (high prior) run first, so the
most paper-worthy nodes are swept earliest (enables early-stop if meaningful
matches thin out).

Run (one shard):
  RDS_HOST=... python3 -m experiments.nl_fl_matching.salient_discovery.run_salient_sweep \
      --manifest .../data/query_manifest.csv --out-dir /gscratch/.../salient_sweep \
      --shard $SLURM_ARRAY_TASK_ID --nshards 200 --k 10
Local smoke test:
  RDS_HOST=... python3 -m experiments.nl_fl_matching.salient_discovery.run_salient_sweep \
      --manifest .../data/query_manifest.csv --out-dir /tmp/sweep_test \
      --shard 0 --nshards 1 --limit 20 --k 10
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "rds"))
from utils.connect import get_rds_connection            # noqa: E402
from experiments.nl_fl_matching import topk             # noqa: E402
from experiments.nl_fl_matching.pools import Stmt        # noqa: E402

EMB = "qwen3-8b"


def load_shard(manifest: Path, shard: int, nshards: int):
    rows = list(csv.DictReader(manifest.open()))
    n = len(rows)
    chunk = (n + nshards - 1) // nshards
    lo, hi = shard * chunk, min((shard + 1) * chunk, n)
    return rows[lo:hi], n, (lo, hi)


def done_sids(out_path: Path) -> set:
    """query_sids already written (checkpoint/resume)."""
    done = set()
    if out_path.exists():
        with out_path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    done.add(json.loads(line)["query_sid"])
                except Exception:
                    pass  # tolerate a torn final line from a preemption
    return done


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--shard", type=int, default=0)
    p.add_argument("--nshards", type=int, default=1)
    p.add_argument("--k", type=int, default=10)
    p.add_argument("--ann-k", type=int, default=50)
    p.add_argument("--limit", type=int, default=None, help="cap queries (smoke test)")
    p.add_argument("--statement-timeout-ms", type=int, default=60000)
    args = p.parse_args()

    rows, total, (lo, hi) = load_shard(args.manifest, args.shard, args.nshards)
    if args.limit:
        rows = rows[: args.limit]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.out_dir / f"salient_sweep_shard{args.shard:04d}.jsonl"

    done = done_sids(out_path)
    todo = [r for r in rows if r["statement_id"] not in done]
    print(f"[shard {args.shard}/{args.nshards}] manifest rows [{lo},{hi}) of {total:,}; "
          f"{len(rows):,} in block, {len(done):,} already done, {len(todo):,} to do -> {out_path}",
          flush=True)
    if not todo:
        print("[shard] nothing to do; exiting 0", flush=True)
        return

    queries = [Stmt(statement_id=r["statement_id"], paper_id=r["paper_id"],
                    slogan_id=r["slogan_id"], name=r["decl_name"], slogan="")
               for r in todo]
    meta = {r["statement_id"]: (r["cls"], r["kind"], r["decl_name"], r["prior"]) for r in todo}

    conn = get_rds_connection("v2")
    conn.autocommit = False
    with conn.cursor() as c:                              # belt-and-suspenders read-only
        c.execute("SET default_transaction_read_only = on")
    conn.commit()

    t0 = time.perf_counter()
    n_written = n_empty = 0
    with out_path.open("a") as fh:
        stream = topk.embedding_topk(
            conn, queries, candidate_pool="all_informals",
            k=args.k, ann_k=args.ann_k, exclusion="statement",
            embedding_model=EMB, statement_timeout_ms=args.statement_timeout_ms,
            show_progress=False,
        )
        for q, results in zip(queries, stream):
            cls, kind, decl, prior = meta[q.statement_id]
            rec = {
                "query_sid": q.statement_id, "cls": cls, "kind": kind,
                "decl_name": decl, "prior": float(prior), "n": len(results),
                "results": [{"rank": r.rank, "cand_sid": r.candidate_statement_id,
                             "cand_pid": r.candidate_paper_id, "sim": round(r.similarity, 5)}
                            for r in results],
            }
            fh.write(json.dumps(rec) + "\n")
            n_written += 1
            if not results:
                n_empty += 1
            if n_written % 200 == 0:
                fh.flush()
                el = time.perf_counter() - t0
                print(f"  [{n_written}/{len(todo)}] {el:.0f}s ({1000*el/n_written:.0f} ms/q, "
                      f"{n_empty} empty)", flush=True)
        stream.close()       # run the generator's finally (rollback) while conn is open
    conn.close()
    el = time.perf_counter() - t0
    print(f"[shard {args.shard}] done: {n_written} written, {n_empty} empty, "
          f"{el:.0f}s ({1000*el/max(n_written,1):.0f} ms/q)", flush=True)


if __name__ == "__main__":
    main()
