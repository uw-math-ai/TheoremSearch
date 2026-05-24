"""Walk informal-dependency neighborhoods around the 500 candidate anchors.

For each anchor sid in top_formalization_candidates.csv:
  - Fetch k=1 OUT (anchor -> X) and k=1 IN (X -> anchor) informal edges
  - For each k=1 neighbor, fetch its k=1 OUT to build k=2 (skipping the anchor)
  - Classify every neighbor's formalization status:
      annotated  = informal_metadata.lean populated
      resolved   = annotated AND at least one decl in `lean` exists in formal_metadata
      matched    = appears as a query in nl_fl_match_pilot with a rank<=3 sim>=0.85 result
      none       = no annotation, no match
  - Aggregate per anchor and write to neighborhoods.csv

Goal: find anchors whose k=1/k=2 neighborhood is densely formalized (so
the Lean-graph supplies many lemmas) but contains a small number of
unformalized "holes" — those holes are the prover-test candidates.

Run from repo root:
    RDS_HOST=theorem-search.cluster-cx0ei6kq0qcn.us-west-2.rds.amazonaws.com \
        python3 -m experiments.nl_fl_matching.analysis.walk_neighborhoods
"""
from __future__ import annotations

import csv
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "rds"))

from utils.connect import get_rds_connection  # noqa: E402


CSV_IN = REPO_ROOT / "experiments/nl_fl_matching/data/top_formalization_candidates.csv"
CSV_OUT = REPO_ROOT / "experiments/nl_fl_matching/data/neighborhoods.csv"
NEIGHBOR_DETAIL_OUT = REPO_ROOT / "experiments/nl_fl_matching/data/neighborhoods_detail.jsonl"
SCHEMA_PATH = REPO_ROOT / "experiments/nl_fl_matching/schema_neighborhoods.sql"
POOL_DESCRIPTOR = "gold_subset_i2f"
MATCH_SIM_THRESHOLD = 0.85


def fetch_edges(conn, sids):
    """Return adjacency:
        out_edges[src_sid] = [dep_sid, ...]
        in_edges[dep_sid]  = [src_sid, ...]
    only for edges where either endpoint is in sids.
    """
    out_edges = defaultdict(list)
    in_edges = defaultdict(list)
    if not sids:
        return out_edges, in_edges
    sids_list = list(sids)
    with conn.cursor() as cur:
        # OUT: src is one of ours
        cur.execute("""
            SELECT src_id::text, dep_id::text
              FROM informal_dependency
             WHERE src_id = ANY(%s::uuid[]) AND dep_id IS NOT NULL
        """, (sids_list,))
        for s, d in cur.fetchall():
            out_edges[s].append(d)
        # IN: dep is one of ours
        cur.execute("""
            SELECT src_id::text, dep_id::text
              FROM informal_dependency
             WHERE dep_id = ANY(%s::uuid[])
        """, (sids_list,))
        for s, d in cur.fetchall():
            in_edges[d].append(s)
    return out_edges, in_edges


def classify_neighbors(conn, neighbor_sids, pilot_index):
    """For each neighbor_sid return a dict with formalization status."""
    out = {}
    if not neighbor_sids:
        return out
    neighbor_list = list(neighbor_sids)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.statement_id::text,
                   s.kind,
                   p.title,
                   p.source,
                   im.ref,
                   im.label,
                   im.lean,
                   LEFT(s.body, 240) AS body_head
              FROM statement s
              JOIN paper p ON p.paper_id = s.paper_id
              LEFT JOIN informal_metadata im ON im.statement_id = s.statement_id
             WHERE s.statement_id = ANY(%s::uuid[])
        """, (neighbor_list,))
        rows = cur.fetchall()

    # Resolve `\lean{...}` annotations: split on comma, check existence in formal_metadata.
    all_decl_tokens = set()
    sid_to_decls = {}
    for sid, kind, title, src, ref, label, lean, body in rows:
        decls = []
        if lean:
            for t in lean.split(","):
                t = t.strip()
                if t:
                    decls.append(t)
                    all_decl_tokens.add(t)
        sid_to_decls[sid] = decls

    existing_decls = set()
    if all_decl_tokens:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT decl_name
                  FROM formal_metadata
                 WHERE decl_name = ANY(%s)
            """, (list(all_decl_tokens),))
            existing_decls = {r[0] for r in cur.fetchall()}

    for sid, kind, title, src, ref, label, lean, body in rows:
        decls = sid_to_decls.get(sid, [])
        resolved_decls = [d for d in decls if d in existing_decls]
        match_hit = pilot_index.get(sid)  # (rank-1 sim, candidate_sid) if any
        out[sid] = {
            "sid": sid,
            "kind": kind,
            "src_paper_title": title,
            "src": src,
            "ref": ref,
            "label": label,
            "lean_annotation": lean or "",
            "body_head": body or "",
            "annotated": bool(decls),
            "n_decl_tokens": len(decls),
            "n_decl_resolved": len(resolved_decls),
            "resolved_decls": resolved_decls,
            "matched_sim": match_hit[0] if match_hit else None,
            "matched_candidate": match_hit[1] if match_hit else None,
        }
    return out


def fetch_pilot_index(conn, sids):
    """For each sid, return (sim, candidate_sid) of its highest-rank-1 match in nl_fl_match_pilot, if any."""
    if not sids:
        return {}
    sids_list = list(sids)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT query_statement_id::text, similarity, candidate_statement_id::text
              FROM nl_fl_match_pilot
             WHERE query_statement_id = ANY(%s::uuid[])
               AND direction = 'i2f' AND rank = 1
               AND similarity >= %s
        """, (sids_list, MATCH_SIM_THRESHOLD))
        return {sid: (sim, cand) for sid, sim, cand in cur.fetchall()}


def status_of(info):
    """Collapse classification into a single label."""
    if info["n_decl_resolved"] >= 1:
        return "resolved"
    if info["annotated"]:
        return "annotated_only"
    if info["matched_sim"] is not None:
        return "matched_only"
    return "none"


def main():
    print(f"[1/5] loading anchors from {CSV_IN}", flush=True)
    anchors = []
    with CSV_IN.open() as fh:
        rd = csv.DictReader(fh)
        for row in rd:
            anchors.append(row["q_sid"])
    print(f"      {len(anchors)} anchors", flush=True)

    conn = get_rds_connection("v2")

    t = time.time()
    print(f"[2/5] fetching anchor k=1 edges", flush=True)
    out1, in1 = fetch_edges(conn, set(anchors))
    print(f"      OUT edges (anchor → ?): {sum(len(v) for v in out1.values())}", flush=True)
    print(f"      IN  edges (? → anchor): {sum(len(v) for v in in1.values())}", flush=True)
    print(f"      elapsed: {time.time() - t:.1f}s", flush=True)

    # k=1 neighbor set
    k1_neighbors_by_anchor = {}
    all_k1 = set()
    for sid in anchors:
        k1 = set(out1.get(sid, [])) | set(in1.get(sid, []))
        k1.discard(sid)
        k1_neighbors_by_anchor[sid] = k1
        all_k1 |= k1
    print(f"      distinct k=1 neighbors across all anchors: {len(all_k1)}", flush=True)

    t = time.time()
    print(f"[3/5] fetching k=2 edges (from k=1 neighbors)", flush=True)
    out2, in2 = fetch_edges(conn, all_k1)
    k2_neighbors_by_anchor = {}
    all_k2 = set()
    for sid in anchors:
        k1 = k1_neighbors_by_anchor[sid]
        k2 = set()
        for n in k1:
            k2 |= set(out2.get(n, []))
            k2 |= set(in2.get(n, []))
        # k=2 excludes k=1 and the anchor itself
        k2 -= k1
        k2.discard(sid)
        k2_neighbors_by_anchor[sid] = k2
        all_k2 |= k2
    print(f"      distinct k=2 (excl k=1) neighbors: {len(all_k2)}", flush=True)
    print(f"      elapsed: {time.time() - t:.1f}s", flush=True)

    all_neighbors = all_k1 | all_k2
    t = time.time()
    print(f"[4/5] classifying {len(all_neighbors)} neighbors", flush=True)
    pilot_index = fetch_pilot_index(conn, all_neighbors)
    print(f"      {len(pilot_index)} neighbors have a rank-1 pilot match @ sim ≥ {MATCH_SIM_THRESHOLD}", flush=True)
    nbr_info = classify_neighbors(conn, all_neighbors, pilot_index)
    print(f"      classified {len(nbr_info)} neighbors", flush=True)
    print(f"      elapsed: {time.time() - t:.1f}s", flush=True)

    print(f"[5/5] aggregating per anchor → {CSV_OUT}", flush=True)
    fieldnames = [
        "anchor_sid", "anchor_paper", "anchor_repo",
        "anchor_sim", "anchor_is_blueprint_gold", "anchor_lean_annotation",
        "k1_total", "k1_resolved", "k1_annotated_only", "k1_matched_only", "k1_none",
        "k2_total", "k2_resolved", "k2_annotated_only", "k2_matched_only", "k2_none",
        "k1_unformalized_examples",
    ]
    # Pull anchor metadata from the CSV again so we can write it through
    anchor_meta = {}
    with CSV_IN.open() as fh:
        rd = csv.DictReader(fh)
        for row in rd:
            anchor_meta[row["q_sid"]] = row

    with CSV_OUT.open("w") as fh, NEIGHBOR_DETAIL_OUT.open("w") as fhd:
        wr = csv.DictWriter(fh, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        wr.writeheader()
        for sid in anchors:
            meta = anchor_meta[sid]
            k1 = k1_neighbors_by_anchor[sid]
            k2 = k2_neighbors_by_anchor[sid]

            def bucket(nset):
                buckets = {"resolved": 0, "annotated_only": 0, "matched_only": 0, "none": 0}
                examples = []
                for n in nset:
                    info = nbr_info.get(n)
                    if not info:
                        buckets["none"] += 1
                        continue
                    st = status_of(info)
                    buckets[st] += 1
                    if st == "none" and len(examples) < 5:
                        examples.append({
                            "sid": n,
                            "ref": info["ref"],
                            "label": info["label"],
                            "kind": info["kind"],
                            "src_paper": info["src_paper_title"],
                            "body_head": info["body_head"][:140],
                        })
                return buckets, examples

            b1, ex1 = bucket(k1)
            b2, _ = bucket(k2)

            wr.writerow({
                "anchor_sid": sid,
                "anchor_paper": meta.get("q_paper_title", ""),
                "anchor_repo": meta.get("q_paper_external_id", ""),
                "anchor_sim": meta.get("similarity", ""),
                "anchor_is_blueprint_gold": meta.get("is_blueprint_gold", ""),
                "anchor_lean_annotation": meta.get("q_lean_annotation", ""),
                "k1_total": len(k1),
                "k1_resolved": b1["resolved"],
                "k1_annotated_only": b1["annotated_only"],
                "k1_matched_only": b1["matched_only"],
                "k1_none": b1["none"],
                "k2_total": len(k2),
                "k2_resolved": b2["resolved"],
                "k2_annotated_only": b2["annotated_only"],
                "k2_matched_only": b2["matched_only"],
                "k2_none": b2["none"],
                "k1_unformalized_examples": json.dumps(ex1),
            })

            # Detailed neighbor view (one JSONL line per anchor)
            fhd.write(json.dumps({
                "anchor_sid": sid,
                "k1_total": len(k1),
                "k2_total": len(k2),
                "k1_neighbors": [
                    {**nbr_info.get(n, {"sid": n}), "_status": status_of(nbr_info[n]) if n in nbr_info else "missing"}
                    for n in k1
                ],
                "k2_neighbors": [
                    {**nbr_info.get(n, {"sid": n}), "_status": status_of(nbr_info[n]) if n in nbr_info else "missing"}
                    for n in k2
                ],
            }) + "\n")

    print(f"      wrote {CSV_OUT}", flush=True)
    print(f"      wrote {NEIGHBOR_DETAIL_OUT}", flush=True)

    print(f"[6/6] upserting per-neighbor rows to RDS table formalization_candidate_neighborhood", flush=True)
    upsert_to_rds(conn, anchors, k1_neighbors_by_anchor, k2_neighbors_by_anchor, nbr_info)


def upsert_to_rds(conn, anchors, k1_by_anchor, k2_by_anchor, nbr_info):
    """Materialize the per-neighbor classifications into a queryable RDS table."""
    with conn.cursor() as cur:
        cur.execute(SCHEMA_PATH.read_text())
    conn.commit()

    rows = []
    for sid in anchors:
        for k, nset in ((1, k1_by_anchor[sid]), (2, k2_by_anchor[sid])):
            for n in nset:
                info = nbr_info.get(n)
                if not info:
                    # Neighbor sid exists in informal_dependency but the statement
                    # itself is missing from `statement`. Record as 'none' with no
                    # metadata rather than silently dropping.
                    rows.append((sid, k, n, "none", None, 0, 0, [], None, None, POOL_DESCRIPTOR))
                    continue
                rows.append((
                    sid, k, n, status_of(info),
                    info["lean_annotation"] or None,
                    info["n_decl_tokens"],
                    info["n_decl_resolved"],
                    info["resolved_decls"],
                    info["matched_sim"],
                    info["matched_candidate"],
                    POOL_DESCRIPTOR,
                ))

    if not rows:
        print("      no rows to write", flush=True)
        return

    from psycopg2.extras import execute_values
    sql = """
        INSERT INTO formalization_candidate_neighborhood (
            anchor_statement_id, k, neighbor_statement_id, status,
            lean_annotation, n_decl_tokens, n_decl_resolved,
            resolved_decls, matched_sim, matched_candidate_id, pool_descriptor
        ) VALUES %s
        ON CONFLICT (anchor_statement_id, k, neighbor_statement_id)
        DO UPDATE SET
            status              = EXCLUDED.status,
            lean_annotation     = EXCLUDED.lean_annotation,
            n_decl_tokens       = EXCLUDED.n_decl_tokens,
            n_decl_resolved     = EXCLUDED.n_decl_resolved,
            resolved_decls      = EXCLUDED.resolved_decls,
            matched_sim         = EXCLUDED.matched_sim,
            matched_candidate_id = EXCLUDED.matched_candidate_id,
            pool_descriptor     = EXCLUDED.pool_descriptor,
            created_at          = now()
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, rows, page_size=500)
    conn.commit()
    print(f"      wrote {len(rows)} rows to formalization_candidate_neighborhood", flush=True)


if __name__ == "__main__":
    main()
