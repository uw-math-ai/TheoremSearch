"""
Evaluate judge-method intrapaper deps against deterministic/heuristic/llm as ground truth.

For each paper that has been judged, compares the set of (src_id, dep_id) edges
found by 'judge' against those found by any of 'deterministic', 'heuristic', 'llm'.

Reports: papers judged, TN, FN, F1.
"""

from rds.utils.connect import get_rds_connection

_BASELINE_METHODS = ("deterministic", "heuristic", "llm")


def evaluate_judge(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT s.paper_id
            FROM informal_dependency d
            JOIN statement s ON s.statement_id = d.src_id
            WHERE 'judge' = ANY(d.methods)
              AND d.cite_key IS NULL
        """)
        paper_ids = [r[0] for r in cur.fetchall()]

    n_papers = len(paper_ids)
    if not n_papers:
        return

    with conn.cursor() as cur:
        cur.execute(
            "SELECT paper_id, statement_id FROM statement WHERE paper_id = ANY(%s::uuid[])",
            (paper_ids,),
        )
        stmts_by_paper: dict = {}
        for paper_id, stmt_id in cur.fetchall():
            stmts_by_paper.setdefault(paper_id, []).append(stmt_id)

        all_stmt_ids = [sid for sids in stmts_by_paper.values() for sid in sids]

        cur.execute("""
            SELECT src_id, dep_id, methods
            FROM informal_dependency
            WHERE cite_key IS NULL
              AND dep_id IS NOT NULL
              AND src_id = ANY(%s::uuid[])
        """, (all_stmt_ids,))
        edge_methods: dict = {}
        for src_id, dep_id, methods in cur.fetchall():
            edge_methods[(str(src_id), str(dep_id))] = methods or []

    judge_edges    = {e for e, m in edge_methods.items() if "judge" in m}
    baseline_edges = {e for e, m in edge_methods.items() if any(bm in m for bm in _BASELINE_METHODS)}

    overlap      = judge_edges & baseline_edges
    parser_only  = baseline_edges - judge_edges
    judge_only   = judge_edges - baseline_edges

    _COLS = list(_BASELINE_METHODS)

    def _method_counts(edges):
        counts: dict = {m: 0 for m in _COLS}
        for edge in edges:
            for m in edge_methods.get(edge, []):
                if m in counts:
                    counts[m] += 1
        return counts

    method_totals  = _method_counts(baseline_edges)
    overlap_counts = _method_counts(overlap)
    parser_counts  = _method_counts(parser_only)

    def _cell(n, total):
        pct = f"{100 * n / total:.1f}%" if total else "N/A"
        return f"{n}/{total} ({pct})"

    tp = len(overlap)
    fp = len(judge_only)
    fn = len(parser_only)
    f1 = 2 * tp / (2 * tp + fp + fn) if (tp or fp or fn) else 0.0
    union = tp + fp + fn

    col_w  = max(len(_cell(method_totals[m], method_totals[m])) for m in _COLS) + 2
    row_w  = len("Parser only")
    header = " " * (row_w + 2) + "".join(m.rjust(col_w) for m in _COLS)
    def _row(label, counts):
        return label.ljust(row_w) + "  " + "".join(
            _cell(counts[m], method_totals[m]).rjust(col_w) for m in _COLS
        )

    fmt_edge = lambda v: f"{v:,} / {union:,} ({100 * v / union:.1f}%)" if union else "N/A"

    print(f"Papers judged:  {n_papers:,}")
    print(f"Overlap:        {fmt_edge(tp)}")
    print(f"Parser only:    {fmt_edge(fn)}")
    print(f"Judge only:     {fmt_edge(fp)}")
    print(f"F1:             {f1:.4f}")
    print()
    print(header)
    print(_row("Overlap",     overlap_counts))
    print(_row("Parser only", parser_counts))


if __name__ == "__main__":
    conn = get_rds_connection("v2")
    evaluate_judge(conn)
